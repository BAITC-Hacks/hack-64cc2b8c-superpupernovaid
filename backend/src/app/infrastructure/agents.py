import asyncio

from app.config import Settings


class DemoOrchestrator:
    async def run(self, prompt: str) -> str:
        return f"Деморежим: запрос «{prompt}» прошёл через API и воркер. Вызов ИИ не выполнялся."


class OpenAIOrchestrator:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def run(self, prompt: str) -> str:
        from agents import Agent, OpenAIResponsesModel, RunConfig, Runner
        from openai import AsyncOpenAI

        async with AsyncOpenAI(
            api_key=self.settings.openai_api_key.get_secret_value(),
            timeout=self.settings.agent_timeout_seconds,
            max_retries=1,
        ) as client:
            model = OpenAIResponsesModel(model=self.settings.openai_model, openai_client=client)
            specialist = Agent(
                name="Prototype analyst",
                handoff_description="Analyzes requirements and proposes implementation steps.",
                instructions="Analyze the request. Give practical steps in the user's language.",
                model=model,
            )
            router = Agent(
                name="Coordinator",
                instructions=(
                    "Answer simple requests directly. For planning and requirements "
                    "analysis, hand off to Prototype analyst. Use the user's language."
                ),
                model=model,
                handoffs=[specialist],
            )
            result = await asyncio.wait_for(
                Runner.run(
                    router, prompt, max_turns=8, run_config=RunConfig(tracing_disabled=True)
                ),
                timeout=self.settings.agent_timeout_seconds,
            )
            return str(result.final_output)
