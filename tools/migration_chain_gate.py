#!/usr/bin/env python3
"""Valida a cadeia de migrations do Alembic.

Invariantes verificados:
- existe pelo menos uma migration;
- toda down_revision aponta para uma revisao que existe;
- nenhuma revisao tem mais de um filho (sem ramificacao);
- existe exatamente uma raiz (down_revision None).

Nao limita a quantidade de arquivos: o projeto cresce, e o que importa e a
cadeia ser linear e completa. O head unico e verificado por `alembic heads`
em tools/validate-public-release.sh.

Uso: python tools/check_migration_chain.py
"""
from __future__ import annotations

import pathlib
import re
import sys

RAIZ = pathlib.Path("backend/alembic/versions")

RE_REVISION = re.compile(r"^revision\s*(?::\s*[^=\n]+)?=\s*['\"]([^'\"]+)['\"]", re.M)
RE_DOWN = re.compile(r"^down_revision\s*(?::\s*[^=\n]+)?=\s*(?:['\"]([^'\"]+)['\"]|None)", re.M)


def main() -> int:
    if not RAIZ.is_dir():
        print(f"diretorio ausente: {RAIZ}", file=sys.stderr)
        return 1

    versoes: dict[str, tuple[str, str | None]] = {}
    for arq in sorted(RAIZ.glob("*.py")):
        texto = arq.read_text(encoding="utf-8")
        rev = RE_REVISION.search(texto)
        down = RE_DOWN.search(texto)
        if not rev:
            print(f"{arq.name}: sem revision declarada", file=sys.stderr)
            return 1
        pai = down.group(1) if (down and down.group(1)) else None
        if rev.group(1) in versoes:
            print(f"{arq.name}: revision duplicada {rev.group(1)}", file=sys.stderr)
            return 1
        versoes[rev.group(1)] = (arq.name, pai)

    if not versoes:
        print("nenhuma migration encontrada", file=sys.stderr)
        return 1

    filhos: dict[str, list[str]] = {}
    for rev, (_nome, pai) in versoes.items():
        if pai is not None:
            filhos.setdefault(pai, []).append(rev)

    erros: list[str] = []
    for rev, (nome, pai) in versoes.items():
        if pai is not None and pai not in versoes:
            erros.append(f"{nome}: down_revision '{pai}' nao existe")
        if len(filhos.get(rev, [])) > 1:
            erros.append(f"{nome}: revisao '{rev}' tem mais de um filho {sorted(filhos[rev])}")

    raizes = [r for r, (_n, p) in versoes.items() if p is None]
    if len(raizes) != 1:
        erros.append(f"esperada 1 raiz (down_revision None), encontradas {len(raizes)}: {sorted(raizes)}")

    if erros:
        for e in erros:
            print(e, file=sys.stderr)
        return 1

    print(f"cadeia linear: {len(versoes)} migrations, raiz {raizes[0]}, sem ramificacao")
    return 0


if __name__ == "__main__":
    sys.exit(main())
