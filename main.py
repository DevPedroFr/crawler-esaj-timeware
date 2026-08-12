"""Orquestrador simples para executar os crawlers.

Fluxo:
 - solicita ao usuário o número CNJ (ou aceita como argv[1])
 - tenta executar o crawler ES AJ (`crawler_esaj`) com o CNJ
 - se qualquer exceção ocorrer, executa o fallback `crawler_eproc`
"""

from __future__ import annotations

import sys
import asyncio
import traceback


def _obter_numero_processo() -> str:
	if len(sys.argv) >= 2 and sys.argv[1].strip():
		return sys.argv[1].strip()

	try:
		return input("Digite o número unificado do processo (CNJ): ").strip()
	except (EOFError, KeyboardInterrupt):
		print()
		return ""


def main() -> None:
	numero = _obter_numero_processo()
	if not numero:
		print("Número do processo não informado. Saindo.")
		sys.exit(1)

	# Tenta executar crawler_esaj primeiro
	try:
		import crawler_esaj

		# Garantir que, se o módulo observar sys.argv, o CNJ esteja presente
		old_argv = sys.argv[:]
		try:
			sys.argv = [old_argv[0], numero]
			crawler_esaj.main()
			return
		finally:
			sys.argv = old_argv
	except Exception as exc:  # noqa: BLE001 - comportamento intencional: qualquer erro cai no fallback
		print(f"Erro no crawler_esaj: {exc}")
		traceback.print_exc()
		print("Executando fallback: crawler_eproc")

	# Fallback: executar crawler_eproc
	try:
		import crawler_eproc

		# Preferir chamada direta ao solver async se disponível
		if hasattr(crawler_eproc, "solve_turnstile"):
			try:
				asyncio.run(crawler_eproc.solve_turnstile(numero))
				return
			except Exception:
				print("Erro ao executar crawler_eproc via solve_turnstile; tentando chamar main().")

		# Último recurso: chamar main() do módulo (pode pedir input novamente)
		try:
			old_argv = sys.argv[:]
			sys.argv = [old_argv[0], numero]
			crawler_eproc.main()
		finally:
			sys.argv = old_argv
	except Exception as exc:
		print(f"Erro ao executar crawler_eproc: {exc}")
		traceback.print_exc()


if __name__ == "__main__":
	try:
		main()
	except KeyboardInterrupt:
		print("\nExecução interrompida pelo usuário.")

