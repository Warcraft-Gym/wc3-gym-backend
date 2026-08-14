import pandas as pd


class ImportUtil:
    @staticmethod
    def isNa[T](value: T) -> T | None:
        if pd.isna(value):
            return None
        return value
