from openai import OpenAI

client = OpenAI(
  base_url="https://openrouter.ai/api/v1",
)

# First API call with reasoning
response = client.chat.completions.create(
  model="nvidia/nemotron-3-ultra-550b-a55b:free",
  messages=[
          {
            "role": "user",
            "content": "How many r's are in the word 'strawberry'?"
          }
        ],
  extra_body={"reasoning": {"enabled": False}}
)

# Extract the assistant message with reasoning_details
response = response.choices[0].message

print(response)