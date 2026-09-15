from langchain_groq import ChatGroq
from langchain.messages import HumanMessage
from dotenv import load_dotenv
import os

load_dotenv()

llm = ChatGroq(model_name="openai/gpt-oss-20b")

message = HumanMessage(
    content="Xin chào"
)

response = llm.invoke([message])
print(response.content)