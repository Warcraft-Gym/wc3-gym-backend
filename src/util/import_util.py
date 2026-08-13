from src.models.enums import Race
import pandas as pd

class ImportUtil():

    @staticmethod
    def isNa(value):
        if pd.isna(value):
            return None
        return value

