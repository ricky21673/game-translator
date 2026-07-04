from abc import ABC, abstractmethod


class Translator(ABC):
    @abstractmethod
    def translate(self, texts: list[str], target_lang: str,
                  source_lang: str | None = None) -> list[str]:
        ...
