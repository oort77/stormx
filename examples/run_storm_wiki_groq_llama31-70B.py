"""
STORM Wiki pipeline powered by Groq llama3-groq-70b-8192-tool-use-preview and You.com search engine.
You need to set up the following environment variables to run this script:
    - GROQ_API_KEY: Groq API key
    - YDC_API_KEY: You.com API key; or, BING_SEARCH_API_KEY: Bing Search API key

Output will be structured as below
args.output_dir/
    topic_name/  # topic_name will follow convention of underscore-connected topic name w/o space and slash
        conversation_log.json           # Log of information-seeking conversation
        raw_search_results.json         # Raw search results from search engine
        direct_gen_outline.txt          # Outline directly generated with LLM's parametric knowledge
        storm_gen_outline.txt           # Outline refined with collected information
        url_to_info.json                # Sources that are used in the final article
        storm_gen_article.txt           # Final article generated
        storm_gen_article_polished.txt  # Polished final article (if args.do_polish_article is True)
"""

import os
import requests
import backoff
from argparse import ArgumentParser
from typing import Optional, Any
from dsp import ERRORS, backoff_hdlr, giveup_hdlr

from knowledge_storm import STORMWikiRunnerArguments, STORMWikiRunner, STORMWikiLMConfigs
from knowledge_storm.lm import GroqModel
from knowledge_storm.rm import YouRM, BingSearch, BraveRM, SerperRM, SearXNGRM
from knowledge_storm.utils import load_api_key


def main(args):
    load_api_key(toml_file_path='secrets.toml')
    lm_configs = STORMWikiLMConfigs()
    groq_kwargs = {
        'api_key': os.getenv("GROQ_API_KEY"),
        'temperature': 1.0,
        'top_p': 0.9,
    }

    # We'll use the same Groq model for all components
    groq_model_name = 'llama-3.1-70b-versatile'

    # Initialize Groq models for different components
    conv_simulator_lm = GroqModel(model=groq_model_name, max_tokens=500, **groq_kwargs)
    question_asker_lm = GroqModel(model=groq_model_name, max_tokens=500, **groq_kwargs)
    outline_gen_lm = GroqModel(model=groq_model_name, max_tokens=400, **groq_kwargs)
    article_gen_lm = GroqModel(model=groq_model_name, max_tokens=700, **groq_kwargs)
    article_polish_lm = GroqModel(model=groq_model_name, max_tokens=4000, **groq_kwargs)

    lm_configs.set_conv_simulator_lm(conv_simulator_lm)
    lm_configs.set_question_asker_lm(question_asker_lm)
    lm_configs.set_outline_gen_lm(outline_gen_lm)
    lm_configs.set_article_gen_lm(article_gen_lm)
    lm_configs.set_article_polish_lm(article_polish_lm)

    engine_args = STORMWikiRunnerArguments(
        output_dir=args.output_dir,
        max_conv_turn=args.max_conv_turn,
        max_perspective=args.max_perspective,
        search_top_k=args.search_top_k,
        max_thread_num=args.max_thread_num,
    )

    # STORM is a knowledge curation system which consumes information from the retrieval module.
    # Currently, the information source is the Internet and we use search engine API as the retrieval module.
    if args.retriever == 'bing':
        rm = BingSearch(bing_search_api=os.getenv('BING_SEARCH_API_KEY'), k=engine_args.search_top_k)
    elif args.retriever == 'you':
        rm = YouRM(ydc_api_key=os.getenv('YDC_API_KEY'), k=engine_args.search_top_k)
    elif args.retriever == 'brave':
        rm = BraveRM(brave_search_api_key=os.getenv('BRAVE_API_KEY'), k=engine_args.search_top_k)
    elif args.retriever == 'serper':
        rm = SerperRM(serper_search_api_key=os.getenv('SERPER_API_KEY'), query_params={"autocorrect": True, "num": 10, "page": 1})
    elif args.retriever == 'searxng':
        rm = SearXNGRM(searxng_api_url=os.getenv('SEARXNG_API_URL'), searxng_api_key=os.getenv('SEARXNG_API_KEY'), k=engine_args.search_top_k)

    runner = STORMWikiRunner(engine_args, lm_configs, rm)

    topic = input('Topic: ')
    runner.run(
        topic=topic,
        do_research=args.do_research,
        do_generate_outline=args.do_generate_outline,
        do_generate_article=args.do_generate_article,
        do_polish_article=args.do_polish_article,
    )
    runner.post_run()
    runner.summary()

if __name__ == '__main__':
    parser = ArgumentParser()
    # global arguments
    parser.add_argument('--output-dir', type=str, default='./results/groq',
                        help='Directory to store the outputs.')
    parser.add_argument('--max-thread-num', type=int, default=3,
                        help='Maximum number of threads to use. The information seeking part and the article generation'
                             'part can speed up by using multiple threads. Consider reducing it if keep getting '
                             '"Exceed rate limit" error when calling LM API.')
    parser.add_argument('--retriever', type=str, choices=['bing', 'you', 'brave','serper','searxng'],
                        help='The search engine API to use for retrieving information.')
    # stage of the pipeline
    parser.add_argument('--do-research', action='store_true',
                        help='If True, simulate conversation to research the topic; otherwise, load the results.')
    parser.add_argument('--do-generate-outline', action='store_true',
                        help='If True, generate an outline for the topic; otherwise, load the results.')
    parser.add_argument('--do-generate-article', action='store_true',
                        help='If True, generate an article for the topic; otherwise, load the results.')
    parser.add_argument('--do-polish-article', action='store_true',
                        help='If True, polish the article by adding a summarization section and (optionally) removing '
                             'duplicate content.')
    # hyperparameters for the pre-writing stage
    parser.add_argument('--max-conv-turn', type=int, default=3,
                        help='Maximum number of questions in conversational question asking.')
    parser.add_argument('--max-perspective', type=int, default=3,
                        help='Maximum number of perspectives to consider in perspective-guided question asking.')
    parser.add_argument('--search-top-k', type=int, default=3,
                        help='Top k search results to consider for each search query.')
    # hyperparameters for the writing stage
    parser.add_argument('--retrieve-top-k', type=int, default=3,
                        help='Top k collected references for each section title.')
    parser.add_argument('--remove-duplicate', action='store_true',
                        help='If True, remove duplicate content from the article.')

    main(parser.parse_args())