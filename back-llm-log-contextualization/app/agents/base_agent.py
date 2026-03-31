from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    """Base class for all agents in the orchestration pipeline."""

    name: str

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    async def run(self, input_data: Any) -> Any:
        """Execute the agent on the given input data.

        Concrete agents should override this method with domain-specific logic.
        """

