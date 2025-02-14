import asyncio
from langchain.document_loaders import PyPDFLoader, DirectoryLoader
from langchain import PromptTemplate
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.vectorstores import FAISS
from langchain.llms import CTransformers
from langchain.chains import RetrievalQA
from typing import Dict, Optional
import chainlit as cl
import re
import requests
import json

GREETING_PATTERNS = [
    r"^hi$|^hello$|^hey$",
    r"^good\s*(morning|afternoon|evening|night)$",
    r"^how\s+are\s+you\??$",
]

DB_FAISS_PATH = "vectorstores/db_faiss"

custom_prompt_template = """
If it is not a medical related question, please respond with "I trained on medical data and can only answer medical questions. Please ask a medical related question."

If it is a medical related question and you don't know the answer, please respond with "I don't know".

Use the following pieces of information to answer the user's question.

Context: {context}
Question: {question}

Only return the helpful answer below and nothing else.
Helpful Answer:
"""


def set_custom_prompt():
    """
    Prompt template for QA retrieval for each vectorstore
    """
    prompt = PromptTemplate(
        template=custom_prompt_template, input_variables=["context", "question"]
    )
    return prompt


# Retrieval QA Chain
def retrieval_qa_chain(llm, prompt, db):
    qa_chain = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=db.as_retriever(search_kwargs={"k": 2}),
        return_source_documents=True,
        chain_type_kwargs={"prompt": prompt},
    )
    return qa_chain


# Loading the model
def load_llm():
    # Load the locally downloaded model here
    llm = CTransformers(
        model="TheBloke/Llama-2-7B-Chat-GGML",
        model_type="llama",
        max_new_tokens=512,
        temperature=0.5,
    )
    return llm


def google_serp_api(query):
    api_key = "API_KEY"
    url = f"https://api.scaleserp.com/search?api_key={api_key}&q={query}"
    response = requests.get(url)
    data = json.loads(response.text)
    return data['organic_results'][0]['snippet'] if data['organic_results'] else "No results found"


# QA Model Function
async def qa_bot():
    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        model_kwargs={"device": "cpu"},
    )
    db = FAISS.load_local(DB_FAISS_PATH, embeddings, allow_dangerous_deserialization=True)
    llm = load_llm()
    qa_prompt = set_custom_prompt()
    qa = retrieval_qa_chain(llm, qa_prompt, db)

    return qa


# Output function
async def final_result(query):
    qa_result = await qa_bot()
    response = await qa_result({"query": query})
    return response


# Add OAuth provider
@cl.oauth_callback
def oauth_callback(
    provider_id: str,
    token: str,
    raw_user_data: Dict[str, str],
    default_user: cl.User,
) -> Optional[cl.User]:
    return default_user


# chainlit code
@cl.on_chat_start
async def start():
    chain = await qa_bot()
    msg = cl.Message(content="Starting the bot...")
    await msg.send()
    msg.content = "Hi, Welcome to Medical Bot. What is your query?"
    await msg.update()

    cl.user_session.set("chain", chain)


@cl.on_message
async def main(message):
    chain = cl.user_session.get("chain")

    for pattern in GREETING_PATTERNS:
        if re.match(pattern, message.content.lower()):
            greeting_response = (
                "Hello! I'm a medical chatbot. How can I assist you today?"
            )
            await cl.Message(content=greeting_response).send()
            return

    cb = cl.AsyncLangchainCallbackHandler(
        stream_final_answer=True, answer_prefix_tokens=["FINAL", "ANSWER"]
    )
    cb.answer_reached = True
    res = await chain.acall(message.content, callbacks=[cb])
    answer = res["result"]

    # if not answer or answer == "I don't know":
    #     answer = google_serp_api(message.content)


if __name__ == "__main__":
    asyncio.run(cl.main())
