from src.database.model.DBEnums import Race
import pandas as pd

class ImportUtil():

    @staticmethod
    def isNa(value):
        if pd.isna(value):
            return None
        return value

