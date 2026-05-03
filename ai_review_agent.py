import argparse
import os

from langgraph.graph import END, START, StateGraph

from Node import Node
from ReviewState import ReviewState
from InputFormatter import InputFormatter

from langgraph.prebuilt import tools_condition, ToolNode
from Tools import think_tool, tavily_search, cross_repository_search

from dotenv import load_dotenv
load_dotenv()
parser = argparse.ArgumentParser()


parser.add_argument("--diff-stats-file", default="", required=False)
parser.add_argument("--code-diff-file", default="", required=False)
parser.add_argument("--comments-file", default="", required=False)

args = parser.parse_args()
input_formatter = InputFormatter()

# Use default files if running locally and no args provided
if not any([args.diff_stats_file, args.code_diff_file, args.comments_file]) and os.getenv("CI") is None:
    args.diff_stats_file = "sample_diff_stats.txt"
    args.code_diff_file = "sample_code_diff.txt"
    args.comments_file = "sample_comments.json"

diff_stats = input_formatter.difference_stats(args.diff_stats_file) if args.diff_stats_file else ""
code_diff = input_formatter.full_code_diff(args.code_diff_file) if args.code_diff_file else ""
comments_for_prompt = input_formatter.parse_comments(args.comments_file) if args.comments_file else ""



Node = Node()

graph = StateGraph(ReviewState)
graph.add_node("orchestrator", Node.orchestratorAgent)
graph.add_node("review_agent_1", Node.ReviewSubAgent1)
graph.add_node("review_finalize", Node.ReviewFinalize)
graph.add_node("conditional_node", Node.conditional_node_to_end_or_review)
graph.add_node("comment_check", Node.check_comments_addressed)
graph.add_node("Summary", Node.generate_summary)
tools = [think_tool, tavily_search, cross_repository_search]
tool_node = ToolNode(tools)
graph.add_node("tools", tool_node)
graph.add_edge(START, "orchestrator")
graph.add_edge("orchestrator", "conditional_node")



def route_review(state: ReviewState) -> str:
    if state.get("action") == "review":
        return "review"
    return "end"

graph.add_conditional_edges(
    "conditional_node",
    route_review, 
    {
        "review": "review_agent_1",
        "end": "comment_check"
    }
)

graph.add_conditional_edges(
    "review_agent_1",
    tools_condition,
    {
        "tools": "tools",
        "__end__": "review_finalize",
    },
)
graph.add_edge("tools", "review_agent_1")
graph.add_edge("review_finalize", "orchestrator")
graph.add_edge("comment_check", "Summary")
graph.add_edge("Summary", END)

app = graph.compile()
print(app.get_graph().draw_ascii())

initial_state = ReviewState(
    diff_stats=diff_stats,
    code_comments=comments_for_prompt,
    full_diff=code_diff,
    summary="",
    plan="",
    action="",
    result="",
    markdown_summary="",
    iteration=0,
    comments_review="",
    thoughts="",
    questions_to_think_through="",
    context_for_thoughts="",
    messages=[] 
)

final_state = app.invoke(initial_state)

with open("final_state.txt", "w", encoding="utf-8") as f:
    f.write(str(final_state))

with open("final_summary.md", "w", encoding="utf-8") as f:
    f.write(final_state["markdown_summary"])

print("plan:", final_state["plan"])
print("result:", final_state["result"])
print("summary:", final_state["summary"])
print("thoughts:", final_state["thoughts"])
print("questions_to_think_through:", final_state["questions_to_think_through"])