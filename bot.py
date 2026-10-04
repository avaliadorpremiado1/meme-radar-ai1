import os
import requests

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


TOKEN = os.environ["TELEGRAM_TOKEN"]
SOLANA_RPC = os.environ["SOLANA_RPC"]


def solana_rpc(method, params):

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }

    response = requests.post(
        SOLANA_RPC,
        json=payload,
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    if "error" in data:
        raise Exception(data["error"])

    return data.get("result")
def get_liquidity_data(token_address):
    url = f"https://api.dexscreener.com/token-pairs/v1/solana/{token_address}"

    response = requests.get(url, timeout=15)
    response.raise_for_status()

    data = response.json()

    if not data:
        return None

    if isinstance(data, list):
        pairs = data
    else:
        pairs = data.get("pairs", [])

    if not pairs:
        return None

    valid_pairs = []

    for pair in pairs:
        liquidity = pair.get("liquidity", {}).get("usd")

        if liquidity is not None:
            valid_pairs.append(pair)

    if not valid_pairs:
        return None

    best_pair = max(
        valid_pairs,
        key=lambda pair: float(
            pair.get("liquidity", {}).get("usd", 0) or 0
        )
    )

    liquidity = float(
        best_pair.get("liquidity", {}).get("usd", 0) or 0
    )

    market_cap = float(
        best_pair.get("marketCap")
        or best_pair.get("fdv")
        or 0
    )

    volume_24h = float(
        best_pair.get("volume", {}).get("h24", 0) or 0
    )

    price_change_24h = float(
        best_pair.get("priceChange", {}).get("h24", 0) or 0
    )

    dex = best_pair.get("dexId", "N/A")

    pair_address = best_pair.get(
        "pairAddress",
        "N/A"
    )

    if market_cap > 0:
        liquidity_ratio = (
            liquidity / market_cap
        ) * 100
    else:
        liquidity_ratio = 0

    return {
        "liquidity": liquidity,
        "market_cap": market_cap,
        "volume_24h": volume_24h,
        "price_change_24h": price_change_24h,
        "liquidity_ratio": liquidity_ratio,
        "dex": dex,
        "pair_address": pair_address
    }
    def get_token_accounts_owned_by(owner_address, token_address):
    result = solana_rpc(
        "getTokenAccountsByOwner",
        [
            owner_address,
            {
                "mint": token_address,
                "encoding": "jsonParsed",
                "commitment": "confirmed"
            }
        ]
    )

    if not result:
        return []

    accounts = result.get("value", [])

    return [
        account.get("pubkey")
        for account in accounts
        if account.get("pubkey")
    ]
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 MEME RADAR AI\n\n"
        "Seu radar inteligente de memecoins.\n\n"
        "Comandos:\n"
        "/top — Melhores oportunidades\n"
        "/analyze — Analisar um token\n"
        "/status — Status do sistema\n"
        "/help — Ajuda"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🟢 MEME RADAR AI está online!\n\n"
        "Scanner: 🟢\n"
        "Dados de mercado: 🟢\n"
        "Segurança: 🟡\n"
        "Wallet Intelligence: 🟡\n"
        "IA: 🟡"
    )


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🔎 Procurando memecoins na Solana...\n"
        "⏳ Filtrando liquidez, volume e movimento..."
    )

    try:

        url = "https://api.dexscreener.com/token-profiles/latest/v1"

        response = requests.get(
            url,
            timeout=15
        )

        if response.status_code != 200:
            await update.message.reply_text(
                "❌ Não consegui buscar os tokens agora."
            )
            return

        profiles = response.json()

        if not isinstance(profiles, list):
            await update.message.reply_text(
                "❌ A resposta da API não veio no formato esperado."
            )
            return

        solana_tokens = []

        for token in profiles:

            if token.get("chainId") != "solana":
                continue

            address = token.get("tokenAddress")

            if not address:
                continue

            solana_tokens.append(address)

        # Remove endereços duplicados
        solana_tokens = list(dict.fromkeys(solana_tokens))

        candidatos = []

        # Limita a quantidade de consultas
        # para evitar excesso de chamadas à API.
        for address in solana_tokens[:30]:

            try:

                token_url = (
                    "https://api.dexscreener.com/latest/dex/tokens/"
                    + address
                )

                token_response = requests.get(
                    token_url,
                    timeout=10
                )

                if token_response.status_code != 200:
                    continue

                token_data = token_response.json()

                pairs = token_data.get("pairs", [])

                pairs = [
                    pair for pair in pairs
                    if pair.get("chainId") == "solana"
                ]

                if not pairs:
                    continue

                # Escolhe o par com maior liquidez
                pair = max(
                    pairs,
                    key=lambda x: (
                        x.get("liquidity", {}).get("usd", 0)
                        or 0
                    )
                )

                base_token = pair.get("baseToken", {})

                name = base_token.get(
                    "name",
                    "Desconhecido"
                )

                symbol = base_token.get(
                    "symbol",
                    "???"
                )

                # Ignora SOL e símbolos claramente relacionados
                # à moeda nativa da rede.
                if symbol.upper() in [
                    "SOL",
                    "WSOL"
                ]:
                    continue

                liquidity = (
                    pair.get("liquidity", {}).get("usd", 0)
                    or 0
                )

                volume = (
                    pair.get("volume", {}).get("h24", 0)
                    or 0
                )

                price_change = (
                    pair.get("priceChange", {}).get("h24", 0)
                    or 0
                )

                market_cap = (
                    pair.get("marketCap", 0)
                    or 0
                )

                # Filtros mínimos
                if liquidity < 15000:
                    continue

                if volume < 10000:
                    continue

                score = 0

                # Liquidez
                if liquidity >= 250000:
                    score += 30
                elif liquidity >= 100000:
                    score += 25
                elif liquidity >= 50000:
                    score += 20
                else:
                    score += 10

                # Volume
                if volume >= 500000:
                    score += 30
                elif volume >= 200000:
                    score += 25
                elif volume >= 50000:
                    score += 20
                else:
                    score += 10

                # Movimento
                if 5 <= price_change <= 50:
                    score += 20
                elif 0 < price_change < 5:
                    score += 10
                elif price_change > 50:
                    # Evita premiar movimentos extremamente esticados
                    score += 5

                # Relação volume/liquidez
                if liquidity > 0:

                    volume_ratio = volume / liquidity

                    if volume_ratio >= 2:
                        score += 20
                    elif volume_ratio >= 1:
                        score += 15
                    elif volume_ratio >= 0.5:
                        score += 10

                candidatos.append({
                    "name": name,
                    "symbol": symbol,
                    "address": address,
                    "liquidity": liquidity,
                    "volume": volume,
                    "price_change": price_change,
                    "market_cap": market_cap,
                    "score": min(score, 100)
                })

            except Exception as token_error:

                print(
                    "ERRO TOKEN:",
                    token_error
                )

                continue

        # Remove possíveis duplicados
        candidatos_unicos = {}

        for token in candidatos:

            address = token["address"]

            if (
                address not in candidatos_unicos
                or token["score"]
                > candidatos_unicos[address]["score"]
            ):
                candidatos_unicos[address] = token

        candidatos = list(
            candidatos_unicos.values()
        )

        candidatos.sort(
            key=lambda x: x["score"],
            reverse=True
        )

        candidatos = candidatos[:5]

        if not candidatos:

            await update.message.reply_text(
                "⚠️ Não encontrei memecoins suficientes "
                "passando pelos filtros atuais."
            )

            return

        message = (
            "🏆 TOP MEMECOINS — SOLANA\n\n"
        )

        for i, token in enumerate(candidatos, 1):

            message += (
                f"{i}️⃣ {token['name']} "
                f"({token['symbol']})\n"
                f"🎯 Score de mercado: "
                f"{token['score']}/100\n"
                f"💧 Liquidez: "
                f"${token['liquidity']:,.0f}\n"
                f"📊 Volume 24h: "
                f"${token['volume']:,.0f}\n"
                f"📈 Movimento 24h: "
                f"{token['price_change']}%\n"
                f"💵 Market Cap: "
                f"${token['market_cap']:,.0f}\n"
                f"🔗 {token['address']}\n\n"
            )

        message += (
            "⚠️ IMPORTANTE\n\n"
            "Esse é apenas um ranking inicial "
            "de mercado.\n\n"
            "❌ Ainda não verifica:\n"
            "• Segurança do contrato\n"
            "• Rug pull\n"
            "• Honeypot\n"
            "• Wallets do dev\n"
            "• Concentração dos holders\n"
            "• Comunidade\n"
            "• Notícias\n\n"
            "🚫 Portanto, nenhum token aqui "
            "é sinal de compra."
        )

        await update.message.reply_text(
            message
        )

    except Exception as error:

        print(
            "ERRO TOP:",
            error
        )

        await update.message.reply_text(
            "❌ Erro ao analisar o mercado.\n\n"
            "Verifique os logs do Railway."
        )


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:
        await update.message.reply_text(
            "🔎 Você precisa colocar o endereço do token.\n\n"
            "Exemplo:\n"
            "/analyze ENDERECO_DO_TOKEN"
        )
        return

    token_address = context.args[0]

    await update.message.reply_text(
        "🔎 Procurando dados do token...\n"
        "⏳ Aguarde..."
    )

    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"

        response = requests.get(
            url,
            timeout=15
        )

        if response.status_code != 200:
            await update.message.reply_text(
                "❌ Não consegui consultar esse token.\n\n"
                "Verifique se o endereço está correto."
            )
            return

        data = response.json()

        pairs = data.get("pairs")

        if not pairs:
            await update.message.reply_text(
                "❌ Não encontrei dados para esse endereço."
            )
            return

        # Procurar o par com maior liquidez
        pairs = [
            pair for pair in pairs
            if pair.get("liquidity")
        ]

        if not pairs:
            await update.message.reply_text(
                "❌ Encontrei o token, mas não encontrei liquidez."
            )
            return

        pair = max(
            pairs,
            key=lambda x: x.get("liquidity", {}).get("usd", 0) or 0
        )

        base_token = pair.get("baseToken", {})

        name = base_token.get("name", "Desconhecido")
        symbol = base_token.get("symbol", "???")

        price = pair.get("priceUsd", "N/D")

        liquidity = pair.get(
            "liquidity", {}
        ).get("usd", 0)

        volume = pair.get(
            "volume", {}
        ).get("h24", 0)

        market_cap = pair.get(
            "marketCap", 0
        )

        fdv = pair.get(
            "fdv", 0
        )

        price_change = pair.get(
            "priceChange", {}
        ).get("h24", 0)

        dex = pair.get(
            "dexId",
            "N/D"
        )

        chain = pair.get(
            "chainId",
            "N/D"
        )

        message = (
            "🔎 ANÁLISE DE MERCADO\n\n"
            f"🪙 {name} ({symbol})\n"
            f"⛓️ Rede: {chain}\n"
            f"🏦 DEX: {dex}\n\n"
            f"💰 Preço: ${price}\n"
            f"💧 Liquidez: ${liquidity:,.0f}\n"
            f"📊 Volume 24h: ${volume:,.0f}\n"
            f"💵 Market Cap: ${market_cap:,.0f}\n"
            f"🏷️ FDV: ${fdv:,.0f}\n"
            f"📈 Variação 24h: {price_change}%\n\n"
            "⚠️ Isso é apenas análise de mercado.\n"
            "Ainda não representa um sinal de compra."
        )

        await update.message.reply_text(message)

    except Exception as error:

        print("ERRO:", error)

        await update.message.reply_text(
            "❌ Aconteceu um erro ao consultar o token.\n\n"
            "Vamos verificar os logs."
        )

async def security(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:

        await update.message.reply_text(
            "🛡️ Você precisa colocar o endereço do token.\n\n"
            "Exemplo:\n"
            "/security ENDERECO_DO_TOKEN"
        )

        return

    token_address = context.args[0]

    await update.message.reply_text(
        "🛡️ SECURITY ENGINE\n\n"
        "🔎 Consultando a blockchain Solana...\n"
        "⏳ Aguarde..."
    )

    try:

        # ==========================================
        # 1. DADOS DO MINT
        # ==========================================

        result = solana_rpc(
            "getAccountInfo",
            [
                token_address,
                {
                    "encoding": "jsonParsed",
                    "commitment": "confirmed"
                }
            ]
        )

        account = result.get("value") if result else None

        if not account:

            await update.message.reply_text(
                "❌ Não encontrei esse endereço "
                "na blockchain Solana."
            )

            return

        data = account.get("data", {})

        parsed = data.get("parsed", {})

        info = parsed.get("info", {})

        mint_authority = info.get(
            "mintAuthority"
        )

        freeze_authority = info.get(
            "freezeAuthority"
        )

        supply = info.get(
            "supply",
            "0"
        )

        decimals = info.get(
            "decimals",
            0
        )

        owner_program = account.get(
            "owner",
            "N/D"
        )

        # ==========================================
        # 2. MINT AUTHORITY
        # ==========================================

        if mint_authority:

            mint_status = "⚠️ ATIVA"

        else:

            mint_status = "✅ REVOGADA"

        # ==========================================
        # 3. FREEZE AUTHORITY
        # ==========================================

        if freeze_authority:

            freeze_status = "⚠️ ATIVA"

        else:

            freeze_status = "✅ REVOGADA"

        # ==========================================
        # 4. HOLDER INTELLIGENCE
        # ==========================================

        largest_result = solana_rpc(
            "getTokenLargestAccounts",
            [
                token_address,
                {
                    "commitment": "confirmed"
                }
            ]
        )

        largest_accounts = []

        if largest_result:

            largest_accounts = (
                largest_result.get("value", [])
            )

        # ==========================================
        # 5. CALCULAR CONCENTRAÇÃO
        # ==========================================

        try:

            supply_number = int(supply)

        except:

            supply_number = 0

        top_10_percentage = 0

        if supply_number > 0:

            for holder in largest_accounts[:10]:

                amount = int(
                    holder.get(
                        "amount",
                        0
                    )
                )

                percentage = (
                    amount / supply_number
                ) * 100

                top_10_percentage += percentage

        # ==========================================
        # 6. CLASSIFICAÇÃO DOS HOLDERS
        # ==========================================

        if top_10_percentage >= 70:

            concentration_status = "🔴 MUITO ALTA"

        elif top_10_percentage >= 50:

            concentration_status = "🟠 ALTA"

        elif top_10_percentage >= 30:

            concentration_status = "🟡 MODERADA"

        else:

            concentration_status = "🟢 BAIXA"

        # ==========================================
        # 7. LIQUIDEZ
        # ==========================================

        liquidity_data = get_liquidity_data(
            token_address
        )

        if liquidity_data:

            liquidity = liquidity_data["liquidity"]

            market_cap = liquidity_data["market_cap"]

            volume_24h = liquidity_data["volume_24h"]

            price_change_24h = (
                liquidity_data["price_change_24h"]
            )

            liquidity_ratio = (
                liquidity_data["liquidity_ratio"]
            )

            dex = liquidity_data["dex"]

            pair_address = (
                liquidity_data["pair_address"]
            )

            if liquidity >= 100000:

                liquidity_status = "🟢 MUITO BOA"

            elif liquidity >= 50000:

                liquidity_status = "🟢 BOA"

            elif liquidity >= 20000:

                liquidity_status = "🟡 MODERADA"

            else:

                liquidity_status = "🔴 BAIXA"

            liquidity_text = (
                "💧 LIQUIDEZ\n"
                f"Liquidez: ${liquidity:,.0f}\n"
                f"Market Cap: ${market_cap:,.0f}\n"
                f"Volume 24h: ${volume_24h:,.0f}\n"
                f"Variação 24h: "
                f"{price_change_24h:+.2f}%\n\n"
                f"Liquidez/MC: "
                f"{liquidity_ratio:.2f}%\n"
                f"DEX: {dex}\n"
                f"Pool: `{pair_address}`\n\n"
                f"Situação: {liquidity_status}\n\n"
            )

        else:

            liquidity_text = (
                "💧 LIQUIDEZ\n"
                "⚠️ Não foi possível encontrar "
                "uma pool válida.\n\n"
            )

        # ==========================================
        # 8. MONTAR RESPOSTA
        # ==========================================

        message = (
            "🛡️ SECURITY ENGINE\n\n"

            f"🪙 Token:\n"
            f"`{token_address}`\n\n"

            "🔐 MINT AUTHORITY\n"
            f"{mint_status}\n\n"

            "🧊 FREEZE AUTHORITY\n"
            f"{freeze_status}\n\n"

            "🪙 SUPPLY\n"
            f"{supply}\n\n"

            "🔢 DECIMAIS\n"
            f"{decimals}\n\n"

            "⚙️ TOKEN PROGRAM\n"
            f"`{owner_program}`\n\n"

            "👥 HOLDER INTELLIGENCE\n"
            f"Contas analisadas: "
            f"{len(largest_accounts)}\n"
            f"Top 10: "
            f"{top_10_percentage:.2f}%\n"
            f"Concentração: "
            f"{concentration_status}\n\n"

            f"{liquidity_text}"

            "📊 PRÓXIMA ANÁLISE\n"
            "• Carteira do dev\n"
            "• Histórico on-chain\n"
            "• Relação entre carteiras\n"
            "• Risco de rug pull\n\n"

            "⚠️ Ainda não é um Security Score."
        )

        await update.message.reply_text(
            message,
            parse_mode="Markdown"
        )

    except Exception as error:

        print(
            "ERRO SECURITY:",
            repr(error)
        )

        await update.message.reply_text(
            "❌ Erro dentro do Security Engine.\n\n"
            f"Detalhes: {error}"
        )
async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🤖 COMANDOS DO MEME RADAR AI\n\n"
        "/start — Iniciar\n"
        "/top — Oportunidades\n"
        "/analyze — Analisar token\n"
        "/security — Segurança do token\n"
        "/status — Status\n"
        "/help — Ajuda"
    )


def main():

    app = Application.builder().token(TOKEN).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("status", status)
    )

    app.add_handler(
        CommandHandler("top", top)
    )

    app.add_handler(
        CommandHandler("analyze", analyze)
    )

    app.add_handler(
        CommandHandler("security", security)
    )

    app.add_handler(
        CommandHandler("help", help_command)
    )

    print("🤖 Meme Radar AI iniciado!")

    app.run_polling()


if __name__ == "__main__":
    main()
