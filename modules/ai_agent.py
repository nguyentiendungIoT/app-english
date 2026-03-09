import os
from google import genai
from google.genai import types


class AIAgent:
    """
    Handles generation of English articles based on user topics using Google Gemini.
    Features Google Search Grounding to get real-time news data.
    """

    def __init__(self, api_key: str = None):
        # Allow passing the key explicitly, or rely on GEMINI_API_KEY environment variable.
        if api_key:
            self.client = genai.Client(api_key=api_key)
        else:
            self.client = genai.Client()  # Assumes GEMINI_API_KEY is set in env

    def generate_news_article(
        self, topic: str, model_id: str = "gemini-2.5-flash"
    ) -> str:
        """
        Generates a concise English news summary about the given topic using Gemini + Search.
        """
        prompt = (
            f"You are a professional English news anchor. "
            f"Write a short, engaging news report in English about the following topic: '{topic}'. "
            f"Requirements:\n"
            f"- Use clear, articulate, and natural English suitable for a text-to-speech engine.\n"
            f"- Keep it concise (around 150-250 words).\n"
            f"- Structure it with a catchy headline, the main news body, and a brief sign-off.\n"
            f"- IMPORTANT: Do not use complex formatting like markdown tables, bolding, or asterisks. "
            f"Just write plain text separated by newlines so the TTS engine can read it smoothly."
        )

        # Enable Google Search grounding
        config = types.GenerateContentConfig(
            tools=[{"google_search": {}}],
            temperature=0.7,
        )

        response = self.client.models.generate_content(
            model=model_id, contents=prompt, config=config
        )

        return response.text


if __name__ == "__main__":
    # Quick self-test (requires GEMINI_API_KEY env var)
    agent = AIAgent()
    print("Generating news about 'Space Exploration'...")
    try:
        article = agent.generate_news_article("Latest discoveries in Space Exploration")
        print("\n--- Generated News ---\n")
        print(article)
    except Exception as e:
        print(f"Error: {e}")
