# Exemplos produtor/consumidor C04

São exemplos executáveis de contrato, não prova de que `backend/api.py` ou a UI
já estejam conectados.

## Proteção da API local

Produtor C04:

```python
from modules.operacao_local import LocalSecurityPolicy

policy = LocalSecurityPolicy(
    bearer_token=token_from_private_user_profile,
    allowed_origins=frozenset(config.CORS_ORIGINS),
    csrf_secret=csrf_secret_from_private_user_profile,
)
policy.authorize(
    method=request.method,
    authorization=request.headers.get("authorization"),
    origin=request.headers.get("origin"),
    csrf_token=request.headers.get("x-modelapro-csrf"),
)
```

Consumidor C01/C06: middleware/dependency aplicada a todas as rotas de dados;
erros viram 401/403 estruturado, nunca fallback sem autenticação. O frontend
recebe segredo por bootstrap local privado, não por fonte, log ou query string.

## Upload antes do parser

```python
from modules.operacao_local import UploadPolicy, validate_upload

metadata = validate_upload(filename, file_bytes, UploadPolicy(max_bytes=25 * 1024 * 1024))
# Somente depois desta linha o importador compatível recebe os bytes.
```

Consumidor C01: usa a metadata/hash no `RequestSpec`/proveniência e ainda aplica
validação semântica do formato. Extensão/magic não tornam uma planilha confiável.

## Licença offline separada do laudo

```python
from modules.commercial_license import load_license

decision = load_license(user_license_path, vendor_public_key)
if not decision.permits("calculate"):
    block_new_calculation()

# Sempre continua disponível para evidência já produzida por licença válida:
can_export = decision.permits("export", evidence_exists=True)
```

Consumidor C02 controla a ação de novo cálculo; C03 apenas apresenta estado da
licença em Ajuda/Sobre e não o transforma em assinatura, grau ou aprovação.

## Backup íntegro

```python
from modules.job_store import JobStore

backup_dir = JobStore.default().export_backup(new_backup_dir)
restored = JobStore.restore_backup(backup_dir, empty_restore_dir)
```

Consumidor operacional: oferece seletor de destino e mostra a verificação antes
de substituir qualquer configuração. Restore sobre store existente e schema
incompatível são recusados.
