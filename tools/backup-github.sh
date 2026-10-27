#!/bin/bash
# Envia todas as branches e tags para o repositório de backup (arquivos ignorados, como .env.*, não são enviados).
set -euo pipefail
cd /root/plataforma-agentes-ia
git push backup --all
git push backup --tags
echo "$(date -Is) backup ok"
