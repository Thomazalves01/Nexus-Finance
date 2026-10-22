NEXUS FINANCE + WHATSAPP BOT (protótipo v0.3)

O QUE FAZ
- Painel e bot usam o mesmo banco de dados SQLite (nexus.db).
- O banco começa vazio: não há receitas, despesas ou investimentos fictícios.
- Registra frases como “Gastei R$ 25,90 no almoço” e “Recebi R$ 320 de salário”.
- Só o número definido em ALLOWED_WHATSAPP_PHONE pode criar movimentações.
- Deduplica IDs de mensagens para não registrar duas vezes em reentregas do webhook.
- Valida a assinatura HMAC-SHA256 do webhook usando META_APP_SECRET.
- Não conecta a bancos e não faz pagamentos.

TESTE LOCAL (Windows PowerShell)
1. Instale Python 3.11 ou superior.
2. Abra a pasta no VS Code e abra o terminal.
3. Execute:
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
4. Copie .env.example para .env e preencha NEXUS_PASSWORD, FLASK_SECRET_KEY e os dados da Meta.
5. Execute: python app.py
6. Abra http://127.0.0.1:5000 e entre com a senha definida em NEXUS_PASSWORD.

WHATSAPP OFICIAL
- Configure a WhatsApp Cloud API em https://developers.facebook.com/.
- O webhook precisa de uma URL HTTPS pública; localhost não é acessível pela Meta.
- Configure a URL pública como https://SEU-DOMINIO/webhook e o token de verificação igual a WHATSAPP_VERIFY_TOKEN.
- Configure META_APP_SECRET com o App Secret da aplicação Meta para validar a assinatura de cada POST.
- Inscreva o aplicativo no campo de webhook “messages”. Siga a documentação atual da Meta.
- Use primeiro o número de teste e autorize seu próprio número como destinatário permitido.
- Use um token da Meta com as permissões necessárias; tokens temporários expiram.

PRODUÇÃO
- Configure APP_ENV=production, SESSION_COOKIE_SECURE=1, uma FLASK_SECRET_KEY aleatória (32+ caracteres), NEXUS_PASSWORD forte (12+ caracteres), META_APP_SECRET e os valores da Meta.
- Hospede com HTTPS. Não exponha o servidor de desenvolvimento diretamente à internet.
- Não publique o .env, tokens, segredos nem o banco nexus.db.
- Faça backups protegidos e teste a restauração.
- O webhook público exige assinatura válida e só aceita movimentações do número permitido.

FRASES DE TESTE
- Recebi R$ 320 de salário
- Gastei R$ 25,90 no almoço
- Paguei R$ 39,90 de assinatura Netflix
- Investi R$ 100 no CDB

LIMITAÇÕES
- Interpretação por regras, sem IA generativa nesta versão.
- Registros do WhatsApp usam a data de hoje e a conta “WhatsApp”.
- Mensagens ambíguas são recusadas.
- Valores de investimentos são cadastros manuais; não há cotação ou conexão bancária.
- Patrimônio exibido é uma estimativa baseada nos lançamentos e investimentos informados, não um saldo bancário verificado.
