import pandas as pd
import time
import random
import os
import re
from typing import Tuple
from camoufox.sync_api import Camoufox
from playwright.sync_api import Page, BrowserContext, TimeoutError as PlaywrightTimeoutError
from pandas import DataFrame

ARQUIVO = "consulta_gtin.xlsx"
LOG = "log_consulta.txt"
STATE = "state.json"
URL = "https://dfe-portal.svrs.rs.gov.br/NFE/Gtin"


def log(msg: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}")
    with open(LOG, "a", encoding="utf-8", errors="ignore") as f:
        f.write(f"{timestamp} - {msg}\n")


def main() -> None:
    df: DataFrame = sheet()

    # Inicia o navegador principal (headless) que vai ficar aberto o tempo todo
    with Camoufox(headless=True, humanize=True) as browser:
        context, page = ensure_logged_in(browser)

        print(f"\n🚀 Iniciando consulta de {len(df)} EANs...\n")

        for i, row in df.iterrows():
            ean: str = str(row["EAN"]).strip()
            status = str(row.get("STATUS", "")).strip().upper()

            if status == "OK":
                continue

            print(f"[{i+1:02d}/{len(df)}] Consultando {ean}")
            try:
                description, ncm, cest = gtin(page, ean)
                df.loc[i, "DESCRICAO"] = description
                df.loc[i, "NCM"] = ncm
                df.loc[i, "CEST"] = cest
                df.loc[i, "STATUS"] = "OK"
                log(f"{ean} → OK")
            except Exception as e:
                df.loc[i, "STATUS"] = "ERRO"
                log(f"{ean} → ERRO: {str(e)}")

            save_sheet(df)

            # Recarrega periodicamente
            if i % 10 == 0 and i > 0:
                print("🔄 Recarregando página para evitar bloqueio...")
                try:
                    page.goto(URL, wait_until="domcontentloaded", timeout=30000)
                except:
                    pass

            time.sleep(random.uniform(4.0, 8.5))

    print("\n✅ Consulta finalizada!")


def ensure_logged_in(browser: Camoufox) -> Tuple[BrowserContext, Page]:
    """Garante que temos uma sessão válida (restaura ou faz login)."""
    if os.path.exists(STATE):
        try:
            ctx = browser.new_context(storage_state=STATE)
            page = ctx.new_page()
            page.goto(URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("#CodGtin", timeout=15000)
            log("✅ Sessão restaurada com sucesso!")
            return ctx, page
        except Exception as e:
            log(f"⚠️ Falha ao restaurar sessão: {e}")

    # Login manual (visível)
    print("\n" + "="*80)
    print("🔑 LOGIN MANUAL NECESSÁRIO")
    print("Janela visível será aberta.")
    print("Faça login + captcha e pressione ENTER no terminal.")
    print("="*80)

    with Camoufox(headless=False, humanize=True) as vis_browser:
        ctx = vis_browser.new_context()
        page = ctx.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)

        input("\n✅ Login concluído? Pressione ENTER... ")

        try:
            page.wait_for_selector("#CodGtin", timeout=60000)
            ctx.storage_state(path=STATE)
            log("✅ Sessão salva com sucesso!")
        except Exception as e:
            log(f"❌ Erro salvando sessão: {e}")
            raise

    # Recria o contexto headless com a nova sessão
    return ensure_logged_in(browser)


def save_sheet(df: DataFrame) -> None:
    df.to_excel(ARQUIVO, index=False)


def sheet() -> DataFrame:
    if not os.path.exists(ARQUIVO):
        df = pd.DataFrame(columns=["EAN", "DESCRICAO", "NCM", "CEST", "STATUS"])
        df.to_excel(ARQUIVO, index=False)
        print(f"Planilha criada: {ARQUIVO}")
        print("Adicione os EANs e execute novamente.")
        exit(0)

    df = pd.read_excel(ARQUIVO, dtype=str)
    df.columns = df.columns.str.strip()
    df = df.fillna("")

    for col in ["DESCRICAO", "NCM", "CEST", "STATUS"]:
        if col not in df.columns:
            df[col] = ""

    print(f"TOTAL DE LINHAS: {len(df)}")
    return df


def ensure_page(page: Page) -> None:
    try:
        if not page.locator("#CodGtin").is_visible(timeout=8000):
            raise PlaywrightTimeoutError()
    except Exception:
        log("🔄 Sessão perdida → Recarregando...")
        page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("#CodGtin", timeout=20000)


def gtin(page: Page, ean: str) -> Tuple[str, str, str]:
    for attempt in range(4):
        try:
            ensure_page(page)
            field = page.locator("#CodGtin")
            field.fill("")
            field.fill(ean)

            page.locator('button[onclick="pesquisa()"]').click()
            page.locator("#ListaGTIN").wait_for(state="visible", timeout=15000)
            page.wait_for_timeout(random.randint(800, 1800))

            return scraping(page)
        except Exception as e:
            log(f"Tentativa {attempt+1}/4 falhou ({ean}): {e}")

            page.screenshot(
                    path=f"erro_{ean}.png",
                    full_page=True
                )

            if attempt < 3:
                page.reload()
                time.sleep(random.uniform(4, 9))
    raise Exception(f"Falha após 4 tentativas para {ean}")


def scraping(page: Page) -> Tuple[str, str, str]:
    text = page.locator("#ListaGTIN").inner_text()
    ncm_match = re.search(r"NCM:\s*(\d+)", text)
    cest_match = re.search(r"CEST:\s*(\d+)", text)
    desc_match = re.search(r"Descrição:\s*([^\n]+)", text)

    return (
        desc_match.group(1).strip() if desc_match else "",
        ncm_match.group(1) if ncm_match else "",
        cest_match.group(1) if cest_match else ""
    )


if __name__ == "__main__":
    main()