# Política de segurança da AuraFi

A AuraFi é um apoio à decisão: não guarda dinheiro, não conecta carteira e não
executa ordens. Mesmo assim, ela guarda contas, perfis de risco e conversas, e
uma falha no site, na API ou no app pode expor esses dados. Esta página diz como
relatar uma falha sem torná-la pública.

## Como relatar uma vulnerabilidade

Use o **reporte privado de vulnerabilidades do GitHub**:

- endereço direto: <https://github.com/vlfbtc/AuraFi/security/advisories/new>;
- ou, no repositório, a aba **Security** e o botão **Report a vulnerability**.

O relato fica visível só para quem o abriu e para os mantenedores, e a conversa
continua no próprio aviso. Não abra issue, discussão ou pull request público
para uma falha de segurança.

Ajuda muito incluir:

- o que foi encontrado e onde (site, API, app iOS ou código deste repositório);
- os passos para reproduzir, com o endereço e a requisição usados;
- o impacto esperado: que dado ou que ação fica exposto;
- se a falha já foi divulgada em outro lugar.

Use só contas e e-mails de teste seus. Não envie dados pessoais de outras
pessoas, códigos de acesso, tokens nem chaves no relato.

Quando a AuraFi tiver caixa de e-mail no próprio domínio, ela também será
listada aqui como canal de contato.

## Escopo

| Dentro do escopo | Endereço |
| --- | --- |
| Site (Web Widget e página da campanha) | https://aurafi-web-widget.onrender.com |
| API | https://aurafi-api.onrender.com |
| Código deste repositório, inclusive o app iOS | https://github.com/vlfbtc/AuraFi |

Fora do escopo: negação de serviço e testes de carga; engenharia social contra
a equipe ou os usuários; e os sistemas dos fornecedores (hospedagem, envio de
e-mail, provedor de IA e fonte de dados de mercado), que têm canais próprios.

Só a versão publicada a partir do branch `main` recebe correções.

## Regras para testar de boa-fé

- não acesse, altere nem apague dados de outras pessoas;
- respeite os limites de requisição da API e pare ao confirmar a falha;
- não use a falha além do necessário para demonstrá-la;
- dê tempo para a correção antes de divulgar.

## O que a AuraFi nunca pede

A AuraFi nunca pede seed phrase, senha ou chave privada. O código de acesso só é
digitado no site ou no app oficiais; ninguém da AuraFi pede esse código por
mensagem, ligação ou e-mail. Qualquer pedido assim é golpe.

O arquivo [`security.txt`](https://aurafi-web-widget.onrender.com/.well-known/security.txt)
do site (RFC 9116) aponta para esta política e para o mesmo canal de reporte.
