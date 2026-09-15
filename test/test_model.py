from langchain_nvidia_ai_endpoints import ChatNVIDIA
from dotenv import load_dotenv
import os

load_dotenv()

client = ChatNVIDIA(
  model="deepseek-ai/deepseek-v4-flash-0731",
  api_key=os.getenv("NVIDIA_API_KEY", "EMPTY"),
  temperature=1,

  max_completion_tokens=16384,
)

lc_messages = [
  {
    "role": "user",
    "content": [
      {
        "type": "text",
        "text": "What is in this image?",
      },
      {
        "type": "image_url",
        "image_url": {
          "url": "https://assets.ngc.nvidia.com/products/api-catalog/phi-3-5-vision/example1b.jpg",
        },
      },
    ],
  },
]

for chunk in client.stream(lc_messages):
  if chunk.additional_kwargs and "reasoning_content" in chunk.additional_kwargs:
    print(chunk.additional_kwargs["reasoning_content"], end="")
  print(chunk.content, end="")