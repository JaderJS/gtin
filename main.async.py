import asyncio
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Tuple

import pandas as pd
from pandas import DataFrame
from camoufox.async_api import AsyncCamoufox
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)


# ============================================================
# CONFIGURAÇÃO DE CAMINHOS
# ============================================================

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"
ERROR_DIR = BASE_DIR / "erros"

ARQUIVO = DATA_DIR / "consulta_gtin.xlsx"
LOG = DATA_DIR / "log_consulta.txt"
STATE = DATA_DIR / "state.json"

URL = "https://dfe-portal.svrs.rs.gov.br/NFE/Gtin"


# Garante que os diretórios existam
DATA_DIR.mkdir(parents=True, exist_ok=True)
ERROR_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# LOG
# ============================================================

def log(*msg: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    message = " ".join(str(item) for item in msg)

    print(f"[{timestamp}] {message}")

    with open(LOG, "a", encoding="utf-8", errors="ignore") as file:
        file.write(f"{timestamp} - {message}\n")


# ============================================================
# PLANILHA
# ============================================================

def save_sheet(df: DataFrame) -> None:
    """
    Salva a planilha atual.
    """
    df.to_excel(ARQUIVO, index=False)


def sheet() -> DataFrame:
    """
    Carrega a planilha de entrada.
    Se não existir, cria uma vazia.
    """

    if not ARQUIVO.exists():
        df = pd.DataFrame(
            columns=[
                "EAN",
                "DESCRICAO",
                "NCM",
                "CEST",
                "STATUS",
            ]
        )

        df.to_excel(ARQUIVO, index=False)

        print(f"Planilha criada: {ARQUIVO}")
        print("Adicione os EANs e execute novamente.")

        return df

    df = pd.read_excel(
        ARQUIVO,
        dtype=str,
    )

    # Remove espaços extras dos nomes das colunas
    df.columns = df.columns.str.strip()

    # Substitui NaN por string vazia
    df = df.fillna("")

    # Garante que todas as colunas necessárias existam
    required_columns = [
        "EAN",
        "DESCRICAO",
        "NCM",
        "CEST",
        "STATUS",
    ]

    for column in required_columns:
        if column not in df.columns:
            df[column] = ""

    # Mantém apenas as colunas esperadas na ordem correta,
    # mas preserva possíveis colunas extras.
    ordered_columns = required_columns + [
        column
        for column in df.columns
        if column not in required_columns
    ]

    df = df[ordered_columns]

    print(f"TOTAL DE LINHAS: {len(df)}")

    return df


# ============================================================
# SESSÃO / LOGIN
# ============================================================

async def validate_session(browser: Browser) -> bool:
    """
    Tenta abrir a página usando o state.json existente.
    Retorna True caso a sessão ainda esteja válida.
    """

    if not STATE.exists():
        return False

    context: BrowserContext | None = None

    try:
        log("🔐 Tentando restaurar sessão existente...")

        context = await browser.new_context(
            storage_state=str(STATE),
        )

        page = await context.new_page()

        await page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=30000,
        )

        await page.wait_for_selector(
            "#CodGtin",
            state="visible",
            timeout=15000,
        )

        log("✅ Sessão restaurada com sucesso!")

        return True

    except Exception as error:
        log(f"⚠️ Sessão inválida ou expirada: {error}")
        return False

    finally:
        if context is not None:
            await context.close()


async def manual_login() -> None:
    """
    Abre o navegador visível para que o usuário faça
    login e resolva o captcha manualmente.
    """

    print("\n" + "=" * 80)
    print("🔑 LOGIN MANUAL NECESSÁRIO")
    print("Uma janela visível do navegador será aberta.")
    print("Faça login e resolva o captcha.")
    print("Depois volte ao terminal e pressione ENTER.")
    print("=" * 80)

    async with AsyncCamoufox(
        headless=False,
        humanize=True,
    ) as browser:

        context = await browser.new_context()
        page = await context.new_page()

        await page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        input("\n✅ Login concluído? Pressione ENTER para continuar... ")

        try:
            await page.wait_for_selector(
                "#CodGtin",
                state="visible",
                timeout=60000,
            )

            await context.storage_state(
                path=str(STATE),
            )

            log(f"✅ Sessão salva em: {STATE}")

        except Exception as error:
            log(f"❌ Erro salvando sessão: {error}")
            raise


async def ensure_session() -> None:
    """
    Garante que exista uma sessão válida.

    Primeiro tenta usar o state.json.
    Se falhar, abre o navegador visível para login manual.
    """

    if STATE.exists():

        async with AsyncCamoufox(
            headless=True,
            humanize=True,
        ) as browser:

            valid = await validate_session(browser)

            if valid:
                return

    log("🔑 Nenhuma sessão válida encontrada.")

    await manual_login()

    # Confirma que o state realmente funciona
    async with AsyncCamoufox(
        headless=True,
        humanize=True,
    ) as browser:

        valid = await validate_session(browser)

        if not valid:
            raise RuntimeError(
                "O login foi realizado, mas a sessão salva não pôde ser restaurada."
            )


# ============================================================
# PÁGINA
# ============================================================

async def ensure_page(page: Page) -> None:
    """
    Verifica se a página está pronta para consulta.
    Se a sessão/página estiver perdida, recarrega.
    """

    try:
        await page.locator("#CodGtin").wait_for(
            state="visible",
            timeout=8000,
        )

    except PlaywrightTimeoutError:
        log("🔄 Página/sessão perdida → Recarregando...")

        await page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=30000,
        )

        await page.wait_for_selector(
            "#CodGtin",
            state="visible",
            timeout=20000,
        )


# ============================================================
# SCRAPING
# ============================================================

async def scraping(page: Page) -> Tuple[str, str, str]:
    """
    Extrai DESCRIÇÃO, NCM e CEST da área #ListaGTIN.
    """

    text = await page.locator("#ListaGTIN").inner_text()

    # Normaliza espaços
    text = text.strip()

    ncm_match = re.search(
        r"NCM:\s*(\d+)",
        text,
        re.IGNORECASE,
    )

    cest_match = re.search(
        r"CEST:\s*(\d+)",
        text,
        re.IGNORECASE,
    )

    desc_match = re.search(
        r"Descrição:\s*([^\n]+)",
        text,
        re.IGNORECASE,
    )

    description = (
        desc_match.group(1).strip()
        if desc_match
        else ""
    )

    ncm = (
        ncm_match.group(1).strip()
        if ncm_match
        else ""
    )

    cest = (
        cest_match.group(1).strip()
        if cest_match
        else ""
    )

    return description, ncm, cest


# ============================================================
# CONSULTA GTIN
# ============================================================

async def gtin(page: Page, ean: str) -> Tuple[str, str, str]:
    """
    Consulta um EAN.
    Faz até 4 tentativas.
    """

    for attempt in range(1, 5):

        try:
            await ensure_page(page)

            field = page.locator("#CodGtin")

            # Limpa o campo
            await field.fill("")

            # Preenche o EAN
            await field.fill(ean)

            # Executa a pesquisa
            await page.locator(
                'button[onclick="pesquisa()"]'
            ).click()

            # Aguarda a área de resultado
            await page.locator("#ListaGTIN").wait_for(
                state="visible",
                timeout=15000,
            )

            # Pequena espera para a página terminar
            # de atualizar os dados
            await page.wait_for_timeout(
                random.randint(800, 1800)
            )

            result = await scraping(page)

            # Caso a página não tenha retornado nada,
            # consideramos a tentativa inválida.
            if not any(result):
                raise RuntimeError(
                    "A consulta não retornou dados."
                )

            return result

        except Exception as error:

            log(
                f"⚠️ Tentativa {attempt}/4 falhou "
                f"({ean}): {error}"
            )

            # Screenshot
            try:
                screenshot_path = (
                    ERROR_DIR / f"erro_{ean}_tentativa_{attempt}.png"
                )

                await page.screenshot(
                    path=str(screenshot_path),
                    full_page=True,
                )

            except Exception as screenshot_error:
                log(
                    f"⚠️ Não foi possível salvar screenshot: "
                    f"{screenshot_error}"
                )

            # Tenta novamente
            if attempt < 4:

                try:
                    await page.reload(
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                except Exception as reload_error:
                    log(
                        f"⚠️ Erro ao recarregar página: "
                        f"{reload_error}"
                    )

                await asyncio.sleep(
                    random.uniform(4.0, 9.0)
                )

    raise RuntimeError(
        f"Falha após 4 tentativas para o EAN {ean}"
    )


# ============================================================
# PROCESSAMENTO PRINCIPAL
# ============================================================

async def process_dataframe(df: DataFrame) -> None:
    """
    Abre um único navegador Camoufox headless
    e processa todos os EANs.
    """

    async with AsyncCamoufox(
        headless=True,
        humanize=True,
    ) as browser:

        context = await browser.new_context(
            storage_state=str(STATE),
        )

        page = await context.new_page()

        await page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=30000,
        )

        await page.wait_for_selector(
            "#CodGtin",
            state="visible",
            timeout=20000,
        )

        print(
            f"\n🚀 Iniciando consulta de "
            f"{len(df)} EANs...\n"
        )

        for i, row in df.iterrows():

            ean = str(row.get("EAN", "")).strip()

            status = (
                str(row.get("STATUS", ""))
                .strip()
                .upper()
            )

            # Ignora linhas já processadas
            if status == "OK":
                continue

            # Ignora linhas sem EAN
            if not ean:
                log(
                    f"Linha {i + 1} ignorada: "
                    f"EAN vazio."
                )
                continue

            print(
                f"[{i + 1:02d}/{len(df)}] "
                f"Consultando {ean}"
            )

            try:

                description, ncm, cest = await gtin(
                    page,
                    ean,
                )

                df.loc[i, "DESCRICAO"] = description
                df.loc[i, "NCM"] = ncm
                df.loc[i, "CEST"] = cest
                df.loc[i, "STATUS"] = "OK"

                log(
                    f"{ean} → OK | "
                    f"Descrição={description} | "
                    f"NCM={ncm} | "
                    f"CEST={cest}"
                )

            except Exception as error:

                df.loc[i, "STATUS"] = "ERRO"

                log(
                    f"{ean} → ERRO: {error}"
                )

            # Salva imediatamente para não perder
            # o progresso caso o processo seja interrompido.
            try:
                save_sheet(df)
            except Exception as error:
                log(
                    f"❌ Erro salvando planilha: {error}"
                )

            # A cada 10 consultas, recarrega a página
            if i % 10 == 0 and i > 0:

                print(
                    "🔄 Recarregando página para "
                    "evitar problemas..."
                )

                try:

                    await page.goto(
                        URL,
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )

                    await page.wait_for_selector(
                        "#CodGtin",
                        state="visible",
                        timeout=15000,
                    )

                except Exception as error:

                    log(
                        f"⚠️ Erro ao recarregar página: "
                        f"{error}"
                    )

            # Intervalo aleatório entre consultas
            await asyncio.sleep(
                random.uniform(4.0, 8.5)
            )

        await context.close()


# ============================================================
# MAIN
# ============================================================

async def main() -> None:

    log("🚀 Iniciando programa...")

    # Carrega planilha
    df = sheet()

    # Não há EANs
    if df.empty:
        print(
            "\nA planilha está vazia."
            "\nAdicione os EANs em:"
        )
        print(ARQUIVO)
        return

    # Verifica se existem EANs para processar
    valid_eans = (
        df["EAN"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    if not valid_eans.astype(bool).any():
        print(
            "\nNenhum EAN foi encontrado na planilha."
        )
        print(f"Arquivo: {ARQUIVO}")
        return

    # Garante sessão válida
    await ensure_session()

    # Processa todos os EANs
    await process_dataframe(df)

    print("\n✅ Consulta finalizada!")
    log("✅ Consulta finalizada!")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print("\n\n⚠️ Programa interrompido pelo usuário.")

    except Exception as error:
        print(
            f"\n❌ Erro fatal: {error}"
        )

        log(
            f"❌ Erro fatal: {error}"
        )

        input(
            "\nPressione ENTER para sair..."
        )