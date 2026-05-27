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
import boto3
from botocore.exceptions import ClientError

def getSecretFromAWSSecretManager(
    secret_name="openai_api_key",
    secret_key="OPEN_AI_API_KEY", 
    region_name="us-east-2",
):
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )    
    try:
        logger.info("Retrieving secret '%s' from AWS Secrets Manager", secret_name)
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        logger.exception("Failed to retrieve secret from AWS Secrets Manager")
        raise e
    secret = get_secret_value_response['SecretString']
    secret_dict = json.loads(secret)
    return secret_dict.get(secret_key)

def get_model(
        temperature: float = 0.0,
        bind_tools: bool = False,
        tool_choice: str | None = None,    
    ):
        try:
            openai_api_key = getSecretFromAWSSecretManager() or os.getenv("OPENAI_API_KEY")
            os.environ["OPENAI_API_KEY"] = openai_api_key
            model = init_chat_model(
                model="gpt-5.4-mini",
                model_provider="openai",   
                temperature=temperature, 
                api_key=openai_api_key
            )
            # if bind_tools:
            #     kwargs = {"tool_choice": tool_choice} if tool_choice else {}
            #     return model.bind_tools([think_tool,tavily_search, cross_repository_search], **kwargs)
            return model
        except Exception as e:
            logger.exception("Failed to initialize the model")
            raise e

def Orchestrator(state: CommentReviewBotState) -> CommentReviewBotState:
    pull_request = state.get("pull_request") or {}
    issue = state.get("issue") or {}
    issue_pull_request = issue.get("pull_request") or {}

    pull_request_url = pull_request.get("url") or issue_pull_request.get("url")
    pull_request_diff_url = (
        pull_request.get("diff_url")
        or issue_pull_request.get("diff_url")
        or pull_request_url
    )
    if not pull_request_url and not pull_request_diff_url:
        raise KeyError("pull_request.url")

    if not pull_request_diff_url:
        raise ValueError("Missing pull_request.diff_url or pull_request.url in webhook state")

    if not pull_request_diff_url.endswith(".diff"):
        pull_request_diff_url = pull_request_diff_url + "/diff"

    print("Fetching pull request diff from:", pull_request_diff_url)
    pull_request_diff = requests.get(pull_request_diff_url).text   
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
    token = getSecretFromAWSSecretManager("GITHUB_TOKEN","GITHUB_TOKEN") or os.getenv("HUB_TOKEN")
    if not token:
        logger.error("Missing GitHub token. Set HUB_TOKEN or GITHUB_TOKEN before posting comments.")
        return

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

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

    number = state.get("number")
    if not number:
        pull_request = state.get("pull_request") or {}
        issue = state.get("issue") or {}
        number = pull_request.get("number") or issue.get("number")
    print("Extracted issue/pr number:", number, state.get("pull_request"), state.get("issue"))
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