import re
import sys
import json
import time
import io
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Optional
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup, FeatureNotFound

try:
    TZ_SAO_PAULO = ZoneInfo("America/Sao_Paulo")
except ZoneInfoNotFoundError:
    TZ_SAO_PAULO = None

BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "logs"

logger = logging.getLogger("tjsp_crawler")
logger.setLevel(logging.INFO)
logger.handlers.clear()

formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(formatter)

log_buffer = io.StringIO()
buffer_handler = logging.StreamHandler(log_buffer)
buffer_handler.setFormatter(formatter)

logger.addHandler(stream_handler)
logger.addHandler(buffer_handler)
logger.propagate = False


def _create_error_session_dir() -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session_dir = LOGS_DIR / f"session_{timestamp}"
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def _persist_error_artifacts(session_dir: Path, resp: Optional[requests.Response], exc: Exception) -> None:
    log_path = session_dir / "crawler.log"
    with log_path.open("w", encoding="utf-8") as f:
        f.write(log_buffer.getvalue())

    exc_path = session_dir / "erro_excecao.txt"
    with exc_path.open("w", encoding="utf-8") as f:
        f.write(f"{type(exc).__name__}: {exc}\n")

    if resp is not None:
        html_path = session_dir / "erro_resposta.html"
        with html_path.open("w", encoding="utf-8") as f:
            f.write(resp.text)

        info_path = session_dir / "erro_resposta.info.txt"
        with info_path.open("w", encoding="utf-8") as f:
            f.write(f"status_code: {resp.status_code}\n")
            f.write(f"url: {resp.url}\n")
            f.write(f"reason: {resp.reason}\n")
            f.write("headers:\n")
            for k, v in resp.headers.items():
                f.write(f"{k}: {v}\n")

BASE_URL = "https://esaj.tjsp.jus.br"
SEARCH_PATH = "/cpopg/search.do"
SHOW_PATH = "/cpopg/show.do"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": f"{BASE_URL}/cpopg/open.do",
}

NUMPROC_RE = re.compile(
    r"^(?P<numero>\d{7})-(?P<digito>\d{2})\.(?P<ano>\d{4})\.(?P<segmento>\d)\.(?P<tribunal>\d{2})\.(?P<foro>\d{4})$"
)

@dataclass
class ProcessoQuery:
    #Dataclass para armazenar e validar dados do processo, número, dígito, ano e foro

    numero_completo: str  
    numero: str = field(init=False)
    digito: str = field(init=False)
    ano: str = field(init=False)
    foro: str = field(init=False)

    def __post_init__(self):
        m = NUMPROC_RE.match(self.numero_completo)
        if not m:
            raise ValueError(
                f"Número de processo fora do padrão CNJ: {self.numero_completo}"
            )
        self.numero = m.group("numero")
        self.digito = m.group("digito")
        self.ano = m.group("ano")
        self.foro = m.group("foro")

    @property
    def numero_digito_ano_unificado(self) -> str:
        return f"{self.numero}-{self.digito}.{self.ano}"


class TJSPCrawler:
    #classe para buscar e processar as informações 
    def __init__(self, delay: float = 2.0, timeout: int = 30):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.delay = delay
        self.timeout = timeout

    def _sleep(self):
        time.sleep(self.delay)

    #prepara o payload para enviar a req
    def _montar_payload(self, query: ProcessoQuery) -> list[tuple[str, str]]:
        return [
            ("conversationId", ""),
            ("cbPesquisa", "NUMPROC"),
            ("numeroDigitoAnoUnificado", query.numero_digito_ano_unificado),
            ("foroNumeroUnificado", query.foro),
            ("dadosConsulta.valorConsultaNuUnificado", query.numero_completo),
            ("dadosConsulta.valorConsultaNuUnificado", "UNIFICADO"),
            ("dadosConsulta.valorConsulta", ""),
            ("dadosConsulta.tipoNuProcesso", "UNIFICADO"),
        ]

    #busca o processo e retorna a resposta e os ids 
    def buscar_processo(self, numero_processo: str) -> tuple[requests.Response, dict]:
        query = ProcessoQuery(numero_processo)
        payload = self._montar_payload(query)

        url = f"{BASE_URL}{SEARCH_PATH}"
        logger.info("Buscando processo %s", query.numero_completo)

        resp = self.session.get(
            url,
            params=payload,
            timeout=self.timeout,
            allow_redirects=False, 
        )

        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location")
            if not location:
                raise RuntimeError("Redirect sem header Location.")
            final_url = location if location.startswith("http") else f"{BASE_URL}{location}"

            parsed = urlparse(final_url)
            qs = parse_qs(parsed.query)
            ids = {k: v[0] for k, v in qs.items()}

            logger.info("Redirecionado (%s) para %s", resp.status_code, final_url)
            self._sleep()

            resp_final = self.session.get(final_url, timeout=self.timeout)
            resp_final.raise_for_status()
        else:
            resp.raise_for_status()
            resp_final = resp
            ids = {}
            logger.warning(
                "Busca não retornou redirect (status %s) - verifique se há "
                "múltiplos resultados ou processo não encontrado.",
                resp.status_code,
            )

        logger.info("Resposta final: %s %s | ids=%s", resp_final.status_code, resp_final.url, ids)

        self._sleep()
        return resp_final, ids

    #salva o html da resposta em um arquivo
    def salvar_html_bruto(self, resp: requests.Response, caminho: str):
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(resp.text)
        logger.info("HTML salvo em %s", caminho)

    #declara a data de coleta no formato iso
    def _data_coleta_iso(self) -> str:
        if TZ_SAO_PAULO is not None:
            return datetime.now(TZ_SAO_PAULO).isoformat()
        return datetime.now().astimezone().isoformat()

    #analisa o html da resposta e extrai os dados
    def parse_cabecalho_processo(self, resp: requests.Response, numero_processo: str) -> dict:
        try:
            soup = BeautifulSoup(resp.text, "lxml")
        except FeatureNotFound:
            logger.warning("Parser 'lxml' não disponível; usando 'html.parser'.")
            soup = BeautifulSoup(resp.text, "html.parser")

        def texto(seletor: str) -> Optional[str]:
            el = soup.select_one(seletor)
            return el.get_text(strip=True) if el else None

        def texto_ou_title(seletor: str) -> Optional[str]:
            el = soup.select_one(seletor)
            if not el:
                return None
            t = el.get_text(strip=True)
            return t or el.get("title")

        def limpar_texto(texto_bruto: Optional[str]) -> Optional[str]:
            if not texto_bruto:
                return None
            return re.sub(r"\s+", " ", texto_bruto).strip()

        def extrair_partes() -> list[dict]:
            partes = []
            for row in soup.select("table#tablePartesPrincipais tr.fundoClaro, table#tablePartesPrincipais tr.fundoEscuro"):
                tipo_el = row.select_one("span.tipoDeParticipacao")
                nome_el = row.select_one("td.nomeParteEAdvogado")
                if not tipo_el or not nome_el:
                    continue

                tipo = limpar_texto(tipo_el.get_text(" ", strip=True))
                texto_completo = nome_el.get_text("\n", strip=True)
                linhas = [linha.strip() for linha in texto_completo.splitlines() if linha.strip()]
                nome = None
                advogados = []

                for linha in linhas:
                    if not nome and linha.lower() not in {"advogado:", "advogada:"} and not linha.lower().startswith("adv"):
                        nome = linha
                    elif linha.lower().startswith("advogado") or linha.lower().startswith("advogada"):
                        continue
                    elif linha and linha not in advogados:
                        advogados.append(linha)

                if not nome:
                    nome = limpar_texto(nome_el.get_text(" ", strip=True))

                partes.append({"polo": tipo, "nome": nome, "advogados": advogados})
            return partes

        #extrai as movimentações
        def extrair_movimentacoes() -> list[dict]:
            movimentacoes = []
            for row in soup.select("tr.containerMovimentacao"):
                data_el = row.select_one("td.dataMovimentacao")
                desc_el = row.select_one("td.descricaoMovimentacao")
                data = limpar_texto(data_el.get_text(" ", strip=True) if data_el else None)
                descricao = limpar_texto(desc_el.get_text(" ", strip=True) if desc_el else None)
                if data or descricao:
                    movimentacoes.append({"data": data, "descricao": descricao})
            return movimentacoes

        #verifica se a tabela pertence a seção de petições intermediárias
        def _row_belongs_to_petições(table: BeautifulSoup) -> bool:
            header_text = " ".join(
                th.get_text(" ", strip=True).lower() for th in table.select("tr th")
            )
            if "data" in header_text and "tipo" in header_text:
                return True

            previous_text = None
            prev = table.find_previous(string=True)
            if prev:
                previous_text = prev.strip().lower()
            return bool(previous_text and "petições" in previous_text)

        #extrai as petições intermediárias e ocorrências
        def extrair_petições_intermediarias() -> dict[str, list[dict]]:
            peticoes_diversas = []
            ocorrencias = []

            for table in soup.select("table"):
                if not _row_belongs_to_petições(table):
                    continue

                for row in table.select("tr.fundoClaro, tr.fundoEscuro"):
                    cols = row.find_all("td")
                    if len(cols) < 2:
                        continue
                    data = limpar_texto(cols[0].get_text(" ", strip=True))
                    tipo = limpar_texto(cols[1].get_text(" ", strip=True))
                    if not data and not tipo:
                        continue

                    item = {
                        "data": data,
                        "tipo": tipo,
                        "peticionante": None,
                        "conteudo_acessivel": False,
                    }

                    if tipo and "petições diversas" in tipo.lower():
                        peticoes_diversas.append(item)
                    else:
                        ocorrencias.append(item)

            return {
                "peticoes_diversas": peticoes_diversas,
                "ocorrencias": ocorrencias,
            }

        valor_acao_bruto = texto("#valorAcaoProcesso")
        valor_acao = re.sub(r"\s+", " ", valor_acao_bruto).strip() if valor_acao_bruto else None

        tags = [
            t.get_text(strip=True)
            for t in soup.select("#containerDadosPrincipaisProcesso .unj-tag")
            if t.get("id") != "labelSituacaoProcesso"
        ]

        peticoes_intermediarias = extrair_petições_intermediarias()

        dados = {
            "numero_processo": numero_processo,
            "data_coleta": self._data_coleta_iso(),
            "classe": texto_ou_title("#classeProcesso"),
            "assunto": texto_ou_title("#assuntoProcesso"),
            "foro": texto_ou_title("#foroProcesso"),
            "vara": texto_ou_title("#varaProcesso"),
            "juiz": texto_ou_title("#juizProcesso"),
            "distribuicao": texto("#dataHoraDistribuicaoProcesso"),
            "controle": texto("#numeroControleProcesso"),
            "area": texto_ou_title("#areaProcesso span"),
            "valor_acao": valor_acao,
            "partes": extrair_partes(),
            "movimentacoes": extrair_movimentacoes(),
            "peticoes_intermediarias": peticoes_intermediarias,
        }
        return dados


def main():
    resp: Optional[requests.Response] = None
    try:
        if len(sys.argv) < 2:
            numero_processo = input("Digite o número unificado do processo (CNJ): ").strip()
            if not numero_processo:
                print("Número do processo não informado.")
                sys.exit(1)
        else:
            numero_processo = sys.argv[1].strip()

        logger.info("Iniciando execução")
        crawler = TJSPCrawler()
        resp, ids = crawler.buscar_processo(numero_processo)

        logger.info("IDs internos do processo: %s", ids)

        dados = crawler.parse_cabecalho_processo(resp, numero_processo)
        output_dir = BASE_DIR / "outputs"
        output_dir.mkdir(exist_ok=True)

        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", numero_processo)
        output_path = output_dir / f"{safe_name}.json"

        with output_path.open("w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
            f.write("\n")

        logger.info("JSON salvo em %s", output_path)
    except Exception as exc:
        error_dir = _create_error_session_dir()
        _persist_error_artifacts(error_dir, resp, exc)
        logger.exception("Erro inesperado durante a execução. Artefatos salvos em %s", error_dir)
        raise

if __name__ == "__main__":
    main()