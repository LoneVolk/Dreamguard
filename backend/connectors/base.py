from abc import ABC, abstractmethod
from typing import List
from models import SleepRecord


class BaseConnector(ABC):
    """
    Абстрактный базовый класс для всех коннекторов.

    Каждый источник данных (Fitbit, Gadgetbridge, CSV, симулятор)
    реализует этот интерфейс и возвращает данные в универсальном
    формате SleepRecord — независимо от исходного формата.

    Для добавления нового источника данных достаточно:
    1. Создать новый файл в папке connectors/
    2. Унаследоваться от BaseConnector
    3. Реализовать метод fetch()
    """

    @abstractmethod
    def fetch(self) -> List[SleepRecord]:
        """
        Получает данные из источника и возвращает
        список универсальных записей SleepRecord.
        """
        pass

    @abstractmethod
    def validate_connection(self) -> bool:
        """
        Проверяет доступность источника данных.
        Возвращает True если подключение успешно.
        """
        pass

    def get_source_name(self) -> str:
        """Название источника данных для логирования"""
        return self.__class__.__name__
