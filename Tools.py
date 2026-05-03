import base64

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage,ToolMessage,AIMessage
from typing import TypedDict
from ReviewState import ReviewState
from langchain.chat_models import init_chat_model
import os
from langchain_tavily import TavilySearch
from langchain_community.tools import ShellTool
from langgraph.graph.message import add_messages
from typing import TypedDict, List

import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
import requests
def get_model(temperature: float = 0.0):
        return init_chat_model(
                model="gpt-5.4-mini",
                model_provider="openai",   
                temperature=temperature,
                api_key=os.getenv("OPENAI_API_KEY")
            )


@tool
def think_tool( question: str, context: str) -> str:
        """
        A tool for thinking through the review process.
        """
        system_message = SystemMessage(content="""
                                       You are a thoughtful assistant that helps analyze the code review process. Your job is to think through the current state of the review and provide insights and next steps based on the information provided. You are asked what thoughts they need to think through in order to make progress on the review process.""")
        human_message = HumanMessage(content=f"""Here is the context for your thoughts:
{context}

        Based on this information, provide your thoughts on what you need to think through in order to make progress on the review process. and Question  is {question}""") 

        class Plan(TypedDict):
            thoughts: str

        gen_model = get_model(temperature=0.0).with_structured_output(Plan)
        response = gen_model.invoke([system_message, human_message])
        print("Thinking...", response["thoughts"])

        return response["thoughts"]

@tool
def tavily_search(query: str) -> str:
    """
    A tool for searching the web using Tavily.
    """
    print(f"Searching the web for: {query}")
    tavily = TavilySearch()
    results = tavily.run(query)
    return str(results)
class SearchResult(TypedDict):
        original_query: str
        previous_tried_queries: List[str]
        results: List[str]
        flag: bool
@tool
def cross_repository_search(query: str,full_state: ReviewState) -> str:
    """
    A tool for performing cross-repository search to find relevant information about potential breaking changes and their impact on the current Frontend codebase.
    If there is any API change that can potentially impact the frontend codebase, it should be detected by this tool and the search results should be analyzed to provide insights on the potential impact and suggestions for improvement if needed.
    """
    print(f"Performing cross-repository search with query: {query}")
    depenedent_repo = os.getenv("DEPENDENT_REPO")
    if not depenedent_repo:
        return "No dependent repository specified. Please set the DEPENDENT_REPO environment variable to perform cross-repository search. Right now we can not be sure if it would break the frontend or not, so we will assume it does break the frontend. Please set the DEPENDENT_REPO environment variable to perform cross-repository search and get more accurate results."
    
    shell_tool = ShellTool()

    class QueryResult(TypedDict):
        query: str 
    state= SearchResult(
        original_query=query,
        previous_tried_queries=[],
        results=[],
        flag=False
    )
    for i in range(3):  # Try up to 3 times
        print(f"Attempt {i+1} for cross-repository search...")
        system_message = SystemMessage(content=f"""
            You are a helpful assistant that performs cross-repository searches to find relevant information about potential breaking changes and their impact on the current Frontend codebase. Your task is to analyze the given query, generate search queries, and execute them to gather information that can help assess the impact of the change.
            """)
        human_message = HumanMessage(content=f"""
            Here is the original query: {query}
            Based on this query, generate a search query that can be used to find relevant information across repositories. If you have already tried some queries, consider them and generate a new one if necessary.
            {{"previous_tried_queries": {state['previous_tried_queries']}, "results": {state['results']}}}
             If you find information that indicates a potential breaking change with impact on the frontend, set the flag to True. Otherwise, keep it False.
             and reposetory is prititaliya/LiveTalk-Fronend, so that should be the suffix for example
             for query "/ws/transcripts/"
             it would become "gh search code /ws/transcripts/ --repo {depenedent_repo}"
        """)
        gen_model = init_chat_model(
                model="gpt-5.4-mini",
                model_provider="openai",   
                temperature=0.0,
                api_key=os.getenv("OPENAI_API_KEY")
            ).with_structured_output(QueryResult)
        response = gen_model.invoke([system_message, human_message])
        print("Generated search query:", response)
        print("Generated search query:", response["query"])
        
        
        try:
            search_results = shell_tool.run({"commands": [response["query"]]})
        except Exception as e:
            search_results = f"search error: {e}"
        print("Search results:", search_results)
        state["previous_tried_queries"] = state.get("previous_tried_queries", []) + [response["query"]]
        state["results"] = state.get("results", []) + [str(search_results)]
        response["results"] = response.get("results", []) + [str(search_results)]

        if search_results:
            pr_url = make_a_patch(search_results, full_state)
            return "‼️‼️‼️‼️THERE IS BREAKING CHANGE WITH POTENTIAL IMPACT ON FRONTEND, WHICH WOULD IMPACT THE FRONTEND AT: " + str(response["results"] ) + " AND A PR HAS BEEN CREATED TO FIX THE ISSUE: " + pr_url
    return "NO BREAKING CHANGE DETECTED WITH POTENTIAL IMPACT ON FRONTEND. SEARCH RESULTS: " + str(response["results"])

def make_a_patch(search_results: str, state: ReviewState):
    repo_name = os.getenv("DEPENDENT_REPO").strip()  # e.g., "owner/repo"
    github_token = os.getenv("HUB_TOKEN")

    # lines= search_results.strip().split(":")
    # print(f"Search results lines: {lines}")
    file_paths = []
    for line in search_results.strip().split("\n")  :
        if line.startswith(repo_name):
            print(f"Found relevant line in search results: {line}")
            file_path = line.strip().split(":")[1].strip()
            file_paths.append(file_path)
   
    headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json"
        }
    file_path = file_paths[0] if file_paths else None
    # check if there is already pr exist 
    print(f"Repo name length: {len(repo_name)}")
    safe_file_name = file_path.split("/")[-1]
    branch_name = f"fix/AUTO-FIX-FROM-REVIEW-AGENT"
    print(f"Making a patch for file: {file_path} in repository: {repo_name}")
    print(f"Making a patch for file: {file_path} in repository: {repo_name}")
    pr_check_response = requests.get(f"https://api.github.com/repos/{repo_name}/pulls", headers=headers)
    if pr_check_response.status_code == 200 and len(pr_check_response.json()) > 0:
            pr_url = pr_check_response.json()[0].get("html_url")
            # now check if pr is from same branch
            if pr_check_response.json()[0].get("head", {}).get("ref") == branch_name:
                print(f"PR already exists for this change: {pr_url}")
                return pr_url
    print(f"Fetching latest commit SHA for 'main'...")
    main_response = requests.get(f"https://api.github.com/repos/{repo_name}/git/ref/heads/main", headers=headers)
    print("Latest commit SHA response:", main_response.json(),f"https://api.github.com/repos/{repo_name}/git/ref/heads/main", headers)
    main_sha = main_response.json()["object"]["sha"]
    print(f"Creating new branch '{branch_name}'...")
    requests.post(f"https://api.github.com/repos/{repo_name}/git/refs", headers=headers, json={
        "ref": f"refs/heads/{branch_name}",
        "sha": main_sha
    })
    for file_path in file_paths:
        print(f"Fetching file content for {file_path}...")
        file_url = f"https://api.github.com/repos/{repo_name}/contents/{file_path}?ref={branch_name}"
        file_response = requests.get(file_url, headers=headers).json()
        print(f"File content response for {file_path}:", file_response)
        file_sha = file_response["sha"]
        current_base64 = file_response["content"].replace("\n", "")
        
        file_content = base64.b64decode(current_base64).decode("utf-8")

        system_prompt = SystemMessage(content=f"""
            You are a helpful assistant that fixes code based on search results indicating a breaking change. 
            Your task is to analyze the breaking change and rewrite the provided file to fix it.
            CRITICAL: Do NOT output a unified diff. Output ONLY the raw, complete, rewritten code for the file. 
            Do not use markdown code blocks (e.g., ```typescript). Just output the exact text of the new file.
            Search results: {search_results}
            Current file content:
            {file_content}
        """)
        human_msg = HumanMessage(content=f"""
            Please rewrite this file to fix the breaking change. Output ONLY the new file content.
            check the new code change from the code diff and ge
            {state['full_diff']}
        """)

        gen_model = init_chat_model(    
            model="gpt-5.4-mini", 
            model_provider="openai",   
            temperature=0.0,
            api_key=os.getenv("OPENAI_API_KEY")
        )   
        
        print("Asking AI to fix the code...")
        response = gen_model.invoke([system_prompt, human_msg])
        new_file_text = response.content
        if new_file_text.startswith("```"):
            new_file_text = "\n".join(new_file_text.split("\n")[1:-1])

        print("Pushing fixed file to GitHub...")
        new_base64 = base64.b64encode(new_file_text.encode("utf-8")).decode("utf-8")
        
        requests.put(file_url, headers=headers, json={
            "message": f"Fixing potential breaking change in {safe_file_name}",
            "content": new_base64,
            "sha": file_sha,
            "branch": branch_name
        })

    print("Creating Pull Request...")
    pr_response = requests.post(f"https://api.github.com/repos/{repo_name}/pulls", headers=headers, json={
            "title": f"Fixing potential breaking change in {safe_file_name}",
            "body": f"Automated fix generated by AI Code Reviewer to address backend contract changes.\n\nContext:\n`{search_results}`",
            "head": branch_name,
            "base": "main"
        })

    if pr_response.status_code == 201:
            pr_url = pr_response.json().get("html_url")
            print(f"Pr Request created: {pr_url}")
            return "PR created to fix the potential breaking change: " + pr_url
    else:
            print(f"Pr Request failed: {pr_response.text}")
            return  pr_response.text.message if pr_response.status_code == 201 else "Failed to create PR: " + pr_response.text

