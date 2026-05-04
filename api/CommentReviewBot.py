import argparse
import os
import json
from langgraph import graph
from langgraph.graph import END, START, StateGraph
from ReviewState import CommentReviewBotState
from Node import Node
from ReviewState import ReviewState
from InputFormatter import InputFormatter
from langchain_core.messages import SystemMessage, HumanMessage,AIMessage,ToolMessage
from langchain.chat_models import init_chat_model
from typing import Literal
from typing_extensions import TypedDict
import logging
logger = logging.getLogger(__name__)
from Tools import think_tool,tavily_search, cross_repository_search
from langgraph.prebuilt import tools_condition, ToolNode
from Tools import think_tool, tavily_search, cross_repository_search
import requests
from dotenv import find_dotenv, load_dotenv
load_dotenv()

def get_model(
        temperature: float = 0.0,
        bind_tools: bool = False,
        tool_choice: str | None = None,    
    ):
        try:

            model = init_chat_model(
                model="gpt-5.4-mini",
                model_provider="openai",   
                temperature=temperature, 
                api_key=os.getenv("OPENAI_API_KEY")
            )
            # if bind_tools:
            #     kwargs = {"tool_choice": tool_choice} if tool_choice else {}
            #     return model.bind_tools([think_tool,tavily_search, cross_repository_search], **kwargs)
            return model
        except Exception as e:
            logger.exception("Failed to initialize the model")
            raise e

def Orchestrator(state: CommentReviewBotState) -> CommentReviewBotState:
    pull_request_diff = requests.get(state['pull_request']['url'] + "/diff").text   
    system_message = SystemMessage(content="You are a Pull Request Question Answering Bot. Your task is to answer questions related to a Pull Request based on the review comments, code changes, and other relevant information. You should provide clear and concise answers to the questions asked by users.")
    user_message = HumanMessage(content="I want you to answer this question related to a Pull Request: " + state['comment']['body'] + ". Here is some information about the Pull Request: " + str(state) + ". The diff of the Pull Request is: " + pull_request_diff)
    class OrchestratorResponse(TypedDict):
        answer: str 
    print("Invoking the model with the following messages:")   
    model = get_model(temperature=0.7, bind_tools=True,).with_structured_output(OrchestratorResponse)
    answer = model.invoke([system_message, user_message])
    if isinstance(answer, dict):
        answer_text = answer.get("answer") or answer.get("text") or json.dumps(answer)
    else:
        answer_text = str(answer)
    print("Model's answer:", answer_text)
    logger.info("Model generated an answer for the comment: %s", answer_text)   
    state['answer'] = answer_text
    return state

def post_an_answer_to_github(state):
    token = os.getenv("HUB_TOKEN") or os.getenv("GITHUB_TOKEN")
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}

    answer_text = state.get("answer") or ""
    if isinstance(answer_text, dict):
        answer_text = answer_text.get("answer") or answer_text.get("text") or json.dumps(answer_text)
    answer_text = str(answer_text).strip()
    if not answer_text:
        print("Empty answer, skipping"); return

    commenter = (state.get("comment") or {}).get("user", {}).get("login") or (state.get("sender") or {}).get("login")
    if commenter:
        body_text = f"@{commenter} {answer_text}"
    else:
        body_text = answer_text

    repo = state.get("repository", {}).get("full_name")
    if not repo:
        print("Missing repository.full_name in state"); return

    number = (state.get("pull_request") or {}).get("number") or (state.get("issue") or {}).get("number") or state.get("issue_number")
    if not number:
        print("No issue/pr number found in state"); return

    url = f"https://api.github.com/repos/{repo}/issues/{number}/comments"
    print("Posting answer to GitHub:", body_text, "->", url)
    response = requests.post(url, json={"body": body_text}, headers=headers)
    if response.status_code == 201:
        print("Answer posted successfully!")
    else:
        print(f"Failed to post answer. Status code: {response.status_code}, Response: {response.text}")

graph = StateGraph(CommentReviewBotState)
graph.add_node("orchestrator", Orchestrator)
graph.add_node("post_an_answer_to_github", post_an_answer_to_github)
graph.add_edge(START, "orchestrator",)
graph.add_edge("orchestrator", "post_an_answer_to_github")
graph.add_edge("post_an_answer_to_github", END)
app =graph.compile()


def run_agent(state: CommentReviewBotState):
    print("Running the agent with initial state:")
    result = app.invoke(state)
    return result