import pandas as pd
import requests
import time

FILE = "consulta_gtin__.xlsx"

df = pd.read_excel(FILE)

df["STATUS"] = df.get("STATUS", "").astype("string")
df["DESCRICAO"] = df.get("DESCRICAO", "").astype("string")
if "MARCA" not in df.columns:
    df["MARCA"] = ""

df["MARCA"] = df["MARCA"].astype("string")

for i, row in df.iterrows():

    ean = str(row["EAN"])

    try:

        url = f"https://world.openfoodfacts.org/api/v0/product/{ean}.json"

        r = requests.get(url, timeout=10)

        data = r.json()

        if data["status"] == 1:

            produto = data["product"]

            descricao = produto.get("product_name", "")
            marca = produto.get("brands", "")

            df.loc[i, "DESCRICAO"] = descricao
            df.loc[i, "MARCA"] = marca
            df.loc[i, "STATUS"] = "OK"

        else:
            df.loc[i, "STATUS"] = "NAO ENCONTRADO"

    except Exception as e:
        df.loc[i, "STATUS"] = "ERRO"

    time.sleep(1)

df.to_excel(FILE, index=False)

print("Consulta finalizada")