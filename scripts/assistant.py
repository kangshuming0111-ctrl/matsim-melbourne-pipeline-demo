"""Query the local assistant without a browser."""
import argparse,json
from wrapper.assistant import ask
from wrapper.ai_provider import status

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('question',nargs='?');parser.add_argument('--engine',choices=['ai','deterministic'],default='ai');parser.add_argument('--status',action='store_true');args=parser.parse_args()
 if args.status:result=status()
 elif args.question:result=ask(args.question,args.engine)
 else:parser.error('Supply a question or --status')
 print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
if __name__=='__main__':main()
