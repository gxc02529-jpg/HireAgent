import json

from hire_agent.evaluation import evaluate_cases


print(json.dumps(evaluate_cases(), ensure_ascii=False, indent=2))
