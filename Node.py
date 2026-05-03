from typing import Literal, TypedDict
from langchain_core import messages
from langchain_core.messages import SystemMessage, HumanMessage,AIMessage,ToolMessage
from langchain.chat_models import init_chat_model
import os
from ReviewState import ReviewState, Summary
from langgraph.graph.message import add_messages

from Tools import think_tool,tavily_search, cross_repository_search
class Node: 
    def get_model(
        self,
        temperature: float = 0.0,
        bind_tools: bool = False,
        tool_choice: str | None = None,
    ):
        model = init_chat_model(
            model="gpt-5.4-mini",
            model_provider="openai",   
            temperature=temperature, 
            api_key=os.getenv("OPENAI_API_KEY")
        )
        if bind_tools:
            kwargs = {"tool_choice": tool_choice} if tool_choice else {}
            return model.bind_tools([think_tool,tavily_search, cross_repository_search], **kwargs)
        return model

    def orchestratorAgent(self, state: ReviewState) -> ReviewState:
        if state["plan"] != "":
            state["iteration"] += 1
            return state
        system_message = SystemMessage(content="""You are the Manager of the code review process. Your job is to analyze the code changes and comments, and create a concise, actionable plan for the review process. 
        Rules for your plan:
        1. Be extremely brief and direct. Avoid generic boilerplate (e.g., "Step 1: Read the code").
        2. Limit the plan to 3 to 5 high-level bullet points.
        3. Focus only on what needs to be addressed based on the diff stats and user comments.
        4. If no user comments are provided, create a brief plan based purely on the diff stats.
        After executing the plan, analyze the results and determine in a single sentence if further iterations are necessary.""")
        human_message = HumanMessage(content=f"""Here is the current state of the review:
        - Diff Stats: {state['diff_stats']}
        - Code Comments: {state['code_comments']}
        - Summary: {state['summary']}
        - Plan: {state['plan']}
        - Action: {state['action']}
        - Result: {state['result']}
        If you are unsure or need to reason about any part of the review, you MUST call the Think tool with a question and the current context before proceeding. Then, provide your concise, bulleted plan of action and next steps.
        You must check that is there any existing API endpoint is changed in the code changes, if there is any API endpoint change, you must include in the plan to check the documentation for the changed API endpoints using the TavilySearch tool to find the relevant documentation and analyze it for any potential impact on the review process And in that case you also need to return API endpoint change flag to true in the response"""
        )

        class Plan(TypedDict):
                plan: str
                API_Change_Flag: bool

        gen_model = self.get_model(temperature=0.0).with_structured_output(Plan)
        response = gen_model.invoke([system_message, human_message])
        state["plan"] = response["plan"]
        state["API_Change_Flag"] = response["API_Change_Flag"]
        state["iteration"] += 1
        return state
    
    def fetch_prompt(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        prompt_path = os.path.join(base_dir, "prompt.txt")
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()

    def ReviewSubAgent1(self, state: ReviewState) -> ReviewState:
        messages = state.get("messages", [])
        if not messages:
            system_message = SystemMessage(content=self.fetch_prompt())
            human_message = HumanMessage(
                content=f"""
                Your Goal is to work on the given Plan:
                {state['plan']}
                and execute it based on the given information about the code changes and comments:
                Diff Stats: {state['diff_stats']}
                Code Comments: {state['code_comments']}
                Code Diff: {state['full_diff']}
                suggestions for improvement based on the previous comments: {state['comments_review']}

                Based on this information, please create a concise summary of the code changes.
                **You MUST return all of the following fields in your response:**
                - summary: A plain English summary of the code changes and issues found.
                - result: A structured list of findings (bugs, vulnerabilities, etc).
                - result_markdown: A markdown-formatted version of the result for better readability (include code blocks, tables, etc).
                - code_suggestions: Suggestions for code improvement based on the previous comments.
                if you need more thoughts to make a decision, use the Think tool to think through the review process and gather your thoughts before creating the summary and results.
                Make sure to check the documentations from search tool if you need to find more information about any topic related to the review process.
                if there is any API endpoint change, you MUST use the cross_repository_search tool Which takes a query as input (eg. if there is some changes like ws/transcripts/ to ws/user_transcripts/ then it should be ws/transcripts/) so basically it takes old code as input to search across frontend repositories to find relevant information about the change and its potential impact, AND YOU MUST INCLUDE THAT ANALYSIS IN THE FINAL REVIEW AND USE WARNING EMOJI IN THE SUMMARY TO HIGHLIGHT THE POTENTIAL IMPACT OF THE API CHANGE ON THE FRONTEND. AND YOU WILL BE GETTING THE FILE NAME FROM THE TOOLCALL RESULT IN THE MESSAGES, SO MAKE SURE TO USE THAT FILE NAME IN THE QUERY FOR CROSS_REPOSITORY_SEARCH TOOL TO CHECK IF THERE IS ANY POTENTIAL IMPACT ON FRONTEND.
                """
                )
      
            messages = add_messages(messages, [system_message, human_message])

        response = self.get_model(
            temperature=0.0,
            bind_tools=True
        ).invoke(messages)
        
        return {"messages": messages + [response]}

    def ReviewFinalize(self, state: ReviewState) -> ReviewState:

        gen_model = self.get_model(temperature=0.0).with_structured_output(Summary)
        response = gen_model.invoke(str(state))
        print("Review SubAgent 1 Response:", response['summary'])
        state["summary"] = response["summary"]
        state["result"] = response["result"]
        state["markdown_summary"] = response["result_markdown"]
        state["comments_review"] = response["code_suggestions"]
        return state




    def conditional_node_to_end_or_review(self, state: ReviewState) -> ReviewState:
        print(f"""
        ========================================================
        Conditional Node Decision: next_step = {state["action"]}
        =======================================================""")
        if state["iteration"] >= 3:
            state["action"] = "end"
            return state

        if state["result"] == "":
            state["action"] = "review"
            return state

        system_message = SystemMessage(
            content="You are the decision maker for the code review process..."
        )
        human_message = HumanMessage(
            content=f"""Here is the information about the code review process:
            Plan: {state['plan']}
            Action: {state['action']}
            Result: {state['result']}

            Based on this information, decide whether to continue reviewing or end."""
            )

        class ReviewDecision(TypedDict):
            next_step: Literal["review", "end"]

        gen_model = self.get_model(temperature=0).with_structured_output(ReviewDecision)
        response = gen_model.invoke([system_message, human_message])
        state["action"] = response["next_step"]
        return state


    def check_comments_addressed(self, state: ReviewState) -> ReviewState:
        print("state in comment check node:", state)
        if len(state["code_comments"]) <= 0:
            return state

        comment_agent = self.get_model(temperature=0)
        system_message = SystemMessage(
            content=("""
                You are an agent that checks whether the code comments provided in the review process have been addressed in the code changes.
                Only Focus on the comments that are between <<COMMENT_START>> and <<COMMENT_END>> markers.
                For each comment, analyze the code changes to determine if the comment has been addressed.
                If a comment has been addressed, mark it as "Addressed". If it has not been addressed, mark it as "Not Addressed" and provide potential suggestions for improvement based on the comment."""
            )
        )
        human_message = HumanMessage(
            content=f"""
            Your goal is to analyze the code comments and the code changes to determine if the comments have been addressed.
            Here is the information about the code changes and comments:
            code_diff: {state['full_diff']}
            Code Comments: {state['code_comments']}
            Based on this information, determine if the comments have been addressed in the code changes. If not, flag that a review is needed and provide potential suggestions for improvement based on the comments.
            Give result in Markdown format for better readability."""
            )

        class CommentCheckResult(TypedDict):
            code_comments_review: str

        agent = comment_agent.with_structured_output(CommentCheckResult)
        response = agent.invoke([system_message, human_message])
        print("Comment Check Agent Response:", response)

        state["comments_review"] = response["code_comments_review"]
        return state


    def generate_summary(self, state: ReviewState) -> ReviewState:
        system_message = SystemMessage(
        content=(
            """
            You are an agent that generates a final summary of the code review process based on the information provided about the review.  
            YOU MUST INCLUDE TOOLCALL RESULTS IN THE SUMMARY IF THERE IS ANY TOOL CALL IN THE MESSAGES. """
        )
    )
        human_message = HumanMessage(
            content=f"""Here is the information about the code review process:
            {state}
            Based on this information, generate a final summary of the code review process.
            Requirements:
            - Include any tool-call results that are relevant to the findings.
            - If cross_repository_search found a frontend impact, mention it clearly.
            - Include a dedicated section for PR comments review.
            - Return a markdown-formatted summary of the results for better readability.
            """
                )

        class FinalSummary(TypedDict):
            final_summary: str

        gen_model = self.get_model(temperature=0).with_structured_output(FinalSummary)
        response = gen_model.invoke([system_message, human_message])
        state["markdown_summary"] = response["final_summary"]
        return state