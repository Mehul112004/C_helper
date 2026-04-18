from abc import ABC, abstractmethod
from typing import Tuple, Optional

class BaseLLMProvider(ABC):
    """
    Abstract base class for all LLM providers.
    """

    @abstractmethod
    def evaluate_prompt(self, system_prompt: str, user_prompt: str) -> Tuple[Optional[str], str]:
        """
        Sends the prompt to the LLM backend.
        
        Args:
            system_prompt (str): The system prompt detailing constraints and roles.
            user_prompt (str): The main user content.
            
        Returns:
            Tuple[Optional[str], str]: 
                - The extracted text content from the LLM (or None if failure).
                - The raw response string for logging purposes.
        """
        pass

    @abstractmethod
    def ping_status(self) -> bool:
        """
        Pings the provider to check if the service is reachable.
        
        Returns:
            bool: True if online and reachable, False otherwise.
        """
        pass
