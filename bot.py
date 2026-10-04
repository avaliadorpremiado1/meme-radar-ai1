import os
import requests

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
)


# =========================================================
# CONFIGURAÇÕES
# =========================================================

TOKEN = os.environ["TELEGRAM_TOKEN"]
SOLANA_RPC = os.environ["SOLANA_RPC"]


# =========================================================
# SOLANA RPC
# =========================================================

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


# =========================================================
# DADOS DE LIQUIDEZ / DEXSCREENER
# =========================================================

def get_liquidity_data(token_address):

    url = (
        "https://api.dexscreener.com/latest/dex/tokens/"
        f"{token_address}"
    )

    response = requests.get(
        url,
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    pairs = data.get(
        "pairs",
        []
    )

    solana_pairs = [
        pair
        for pair in pairs
        if pair.get("chainId") == "solana"
    ]

    if not solana_pairs:
        return None

    # Escolher o par com maior liquidez
    best_pair = max(
        solana_pairs,
        key=lambda pair: (
            pair.get(
                "liquidity",
                {}
            ).get("usd") or 0
        )
    )

    liquidity = (
        best_pair
        .get("liquidity", {})
        .get("usd") or 0
    )

    market_cap = (
        best_pair.get("marketCap")
        or best_pair.get("fdv")
        or 0
    )

    volume_24h = (
        best_pair
        .get("volume", {})
        .get("h24") or 0
    )

    price_change_24h = (
        best_pair
        .get("priceChange", {})
        .get("h24") or 0
    )

    dex_id = best_pair.get(
        "dexId",
        "N/D"
    )

    pair_address = best_pair.get(
        "pairAddress",
        "N/D"
    )

    return {
        "liquidity": float(liquidity),
        "market_cap": float(market_cap),
        "volume_24h": float(volume_24h),
        "price_change_24h": float(price_change_24h),
        "dex_id": dex_id,
        "pair_address": pair_address
    }


# =========================================================
# IDENTIFICAR OWNER DE UMA TOKEN ACCOUNT
# =========================================================

def get_token_account_owner(token_account_address):

    result = solana_rpc(
        "getAccountInfo",
        [
            token_account_address,
            {
                "encoding": "jsonParsed",
                "commitment": "confirmed"
            }
        ]
    )

    if not result:
        return None

    account = result.get(
        "value"
    )

    if not account:
        return None

    data = account.get(
        "data",
        {}
    )

    parsed = data.get(
        "parsed",
        {}
    )

    info = parsed.get(
        "info",
        {}
    )

    owner = info.get(
        "owner"
    )

    return owner


# =========================================================
# VERIFICAR SE É A POOL
# =========================================================

def is_liquidity_pool_wallet(
    wallet_address,
    pair_address
):

    if not wallet_address:
        return False

    if not pair_address:
        return False

    if pair_address == "N/D":
        return False

    return wallet_address == pair_address


# =========================================================
# COMANDO START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🤖 MEME RADAR AI\n\n"
        "Bot online e conectado à Solana.\n\n"
        "Comandos disponíveis:\n\n"
        "/top - Melhores oportunidades de mercado\n"
        "/security ENDERECO - Análise de segurança\n"
        "/help - Ajuda"
    )


# =========================================================
# COMANDO HELP
# =========================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🤖 MEME RADAR AI\n\n"

        "📊 /top\n"
        "Mostra os tokens com melhor atividade "
        "de mercado.\n\n"

        "🛡️ /security ENDERECO\n"
        "Analisa segurança, autoridades, holders "
        "e liquidez.\n\n"

        "Exemplo:\n"
        "/security ENDERECO_DO_TOKEN\n\n"

        "⚠️ As análises são informativas e não "
        "garantem lucro."
    )


# =========================================================
# COMANDO TOP
# =========================================================

async def top(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "📡 MEME RADAR AI\n\n"
        "🔎 Procurando oportunidades na Solana...\n"
        "⏳ Aguarde..."
    )

    try:

        profiles_url = (
            "https://api.dexscreener.com/"
            "token-profiles/latest/v1"
        )

        response = requests.get(
            profiles_url,
            timeout=20
        )

        response.raise_for_status()

        profiles = response.json()

        candidates = []

        for profile in profiles:

            if profile.get(
                "chainId"
            ) != "solana":

                continue

            token_address = profile.get(
                "tokenAddress"
            )

            if not token_address:
                continue

            try:

                token_url = (
                    "https://api.dexscreener.com/"
                    "latest/dex/tokens/"
                    f"{token_address}"
                )

                token_response = requests.get(
                    token_url,
                    timeout=15
                )

                token_response.raise_for_status()

                token_data = (
                    token_response.json()
                )

                pairs = token_data.get(
                    "pairs",
                    []
                )

                solana_pairs = [
                    pair
                    for pair in pairs
                    if pair.get(
                        "chainId"
                    ) == "solana"
                ]

                if not solana_pairs:
                    continue

                best_pair = max(
                    solana_pairs,
                    key=lambda pair: (
                        pair.get(
                            "liquidity",
                            {}
                        ).get("usd") or 0
                    )
                )

                base_token = best_pair.get(
                    "baseToken",
                    {}
                )

                symbol = base_token.get(
                    "symbol",
                    "N/D"
                )

                name = base_token.get(
                    "name",
                    "Token"
                )

                # Ignorar SOL / WSOL
                if symbol.upper() in [
                    "SOL",
                    "WSOL"
                ]:

                    continue

                liquidity = (
                    best_pair
                    .get("liquidity", {})
                    .get("usd") or 0
                )

                volume = (
                    best_pair
                    .get("volume", {})
                    .get("h24") or 0
                )

                price_change = (
                    best_pair
                    .get("priceChange", {})
                    .get("h24") or 0
                )

                market_cap = (
                    best_pair.get(
                        "marketCap"
                    )
                    or best_pair.get(
                        "fdv"
                    )
                    or 0
                )

                # Filtros mínimos
                if liquidity < 15000:
                    continue

                if volume < 10000:
                    continue

                # =================================================
                # SCORE DE MERCADO
                # =================================================

                liquidity_score = min(
                    liquidity / 50000 * 30,
                    30
                )

                volume_score = min(
                    volume / 500000 * 30,
                    30
                )

                # Evitar premiar demais movimentos parabólicos
                if price_change >= 50:

                    movement_score = 5

                elif price_change > 0:

                    movement_score = min(
                        price_change / 10,
                        20
                    )

                else:

                    movement_score = 0

                volume_liquidity_ratio = (
                    volume / liquidity
                    if liquidity > 0
                    else 0
                )

                ratio_score = min(
                    volume_liquidity_ratio / 10 * 20,
                    20
                )

                score = (
                    liquidity_score
                    + volume_score
                    + movement_score
                    + ratio_score
                )

                candidates.append({
                    "name": name,
                    "symbol": symbol,
                    "address": token_address,
                    "liquidity": liquidity,
                    "volume": volume,
                    "price_change": price_change,
                    "market_cap": market_cap,
                    "score": score
                })

            except Exception as token_error:

                print(
                    "ERRO TOKEN TOP:",
                    repr(token_error)
                )

                continue

            if len(candidates) >= 30:
                break

        candidates.sort(
            key=lambda item: item["score"],
            reverse=True
        )

        top_tokens = candidates[:5]

        if not top_tokens:

            await update.message.reply_text(
                "❌ Não encontrei tokens suficientes "
                "com os filtros atuais."
            )

            return

        message = (
            "🔥 MEME RADAR AI — TOP 5\n\n"

            "Ranking baseado em dados de mercado.\n"
            "Ainda não considera segurança, "
            "carteiras, comunidade ou notícias.\n\n"
        )

        for index, token in enumerate(
            top_tokens,
            start=1
        ):

            message += (
                f"{index}️⃣ {token['name']} "
                f"({token['symbol']})\n"

                f"📊 Score mercado: "
                f"{token['score']:.0f}/100\n"

                f"💧 Liquidez: "
                f"${token['liquidity']:,.0f}\n"

                f"📈 Volume 24h: "
                f"${token['volume']:,.0f}\n"

                f"🚀 Movimento: "
                f"{token['price_change']:.2f}%\n"

                f"💰 MC: "
                f"${token['market_cap']:,.0f}\n"

                f"🪙 `{token['address']}`\n\n"
            )

        message += (
            "⚠️ IMPORTANTE\n"

            "Esse ranking NÃO é sinal de compra.\n"

            "Um token pode ter volume alto e ainda "
            "ser extremamente arriscado.\n\n"

            "Próxima etapa: Security + Wallet "
            "Intelligence."
        )

        await update.message.reply_text(
            message,
            parse_mode="Markdown"
        )

    except Exception as error:

        print(
            "ERRO TOP:",
            repr(error)
        )

        await update.message.reply_text(
            "❌ Erro no Market Engine.\n\n"
            f"Detalhes: {error}"
        )


# =========================================================
# COMANDO SECURITY
# =========================================================

async def security(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "🛡️ Você precisa colocar o endereço "
            "do token.\n\n"

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

        # =====================================================
        # 1. DADOS DO MINT
        # =====================================================

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

        account = (
            result.get("value")
            if result
            else None
        )

        if not account:

            await update.message.reply_text(
                "❌ Não encontrei esse endereço "
                "na blockchain Solana."
            )

            return

        data = account.get(
            "data",
            {}
        )

        parsed = data.get(
            "parsed",
            {}
        )

        info = parsed.get(
            "info",
            {}
        )

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

        # =====================================================
        # 2. MINT AUTHORITY
        # =====================================================

        if mint_authority:

            mint_status = "⚠️ ATIVA"

        else:

            mint_status = "✅ REVOGADA"

        # =====================================================
        # 3. FREEZE AUTHORITY
        # =====================================================

        if freeze_authority:

            freeze_status = "⚠️ ATIVA"

        else:

            freeze_status = "✅ REVOGADA"

        # =====================================================
        # 4. HOLDER ACCOUNTS
        # =====================================================

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
                largest_result.get(
                    "value",
                    []
                )
            )

        # =====================================================
        # 5. DADOS DE LIQUIDEZ
        # =====================================================

        liquidity_data = get_liquidity_data(
            token_address
        )

        liquidity = 0
        market_cap = 0
        volume_24h = 0
        price_change = 0
        dex_id = "N/D"
        pair_address = "N/D"

        if liquidity_data:

            liquidity = (
                liquidity_data["liquidity"]
            )

            market_cap = (
                liquidity_data["market_cap"]
            )

            volume_24h = (
                liquidity_data["volume_24h"]
            )

            price_change = (
                liquidity_data["price_change_24h"]
            )

            dex_id = (
                liquidity_data["dex_id"]
            )

            pair_address = (
                liquidity_data["pair_address"]
            )

        # =====================================================
        # 6. HOLDER INTELLIGENCE 2.0
        # =====================================================

        try:

            supply_number = int(
                supply
            )

        except Exception:

            supply_number = 0

        # -----------------------------------------------------
        # CONCENTRAÇÃO BRUTA
        # -----------------------------------------------------

        top_10_percentage = 0

        # -----------------------------------------------------
        # HOLDERS
        # -----------------------------------------------------

        holder_wallets = {}

        # -----------------------------------------------------
        # POOLS IDENTIFICADAS
        # -----------------------------------------------------

        liquidity_wallets = {}

        # -----------------------------------------------------
        # DETALHES
        # -----------------------------------------------------

        holder_details = []

        if supply_number > 0:

            for holder in largest_accounts[:10]:

                token_account = holder.get(
                    "address"
                )

                amount = int(
                    holder.get(
                        "amount",
                        0
                    )
                )

                percentage = (
                    amount / supply_number
                ) * 100

                # Concentração bruta
                top_10_percentage += percentage

                owner = None

                try:

                    owner = (
                        get_token_account_owner(
                            token_account
                        )
                    )

                except Exception as owner_error:

                    print(
                        "ERRO OWNER:",
                        repr(owner_error)
                    )

                if owner:

                    # =================================================
                    # VERIFICAR SE É A POOL
                    # =================================================

                    is_pool = (
                        is_liquidity_pool_wallet(
                            owner,
                            pair_address
                        )
                    )

                    # =================================================
                    # POOL
                    # =================================================

                    if is_pool:

                        if owner not in liquidity_wallets:

                            liquidity_wallets[owner] = 0

                        liquidity_wallets[owner] += (
                            percentage
                        )

                        holder_details.append({
                            "token_account": (
                                token_account
                            ),
                            "owner": owner,
                            "percentage": percentage,
                            "type": "liquidity_pool"
                        })

                    # =================================================
                    # HOLDER NORMAL
                    # =================================================

                    else:

                        if owner not in holder_wallets:

                            holder_wallets[owner] = 0

                        holder_wallets[owner] += (
                            percentage
                        )

                        holder_details.append({
                            "token_account": (
                                token_account
                            ),
                            "owner": owner,
                            "percentage": percentage,
                            "type": "holder"
                        })

                else:

                    holder_details.append({
                        "token_account": (
                            token_account
                        ),
                        "owner": None,
                        "percentage": percentage,
                        "type": "unknown"
                    })

        # =====================================================
        # 6.1 CONCENTRAÇÃO DA LIQUIDEZ
        # =====================================================

        pool_percentage = sum(
            liquidity_wallets.values()
        )

        # =====================================================
        # 6.2 CONCENTRAÇÃO REAL
        # =====================================================

        real_holder_percentage = sum(
            holder_wallets.values()
        )

        # =====================================================
        # 6.3 WALLETS ÚNICAS
        # =====================================================

        unique_wallets = len(
            holder_wallets
        )

        # =====================================================
        # 6.4 ORDENAR HOLDERS REAIS
        # =====================================================

        sorted_wallets = sorted(
            holder_wallets.items(),
            key=lambda item: item[1],
            reverse=True
        )

        # =====================================================
        # 6.5 PRINCIPAIS HOLDERS
        # =====================================================

        top_wallets_message = ""

        if sorted_wallets:

            for index, wallet in enumerate(
                sorted_wallets[:5],
                start=1
            ):

                wallet_address = wallet[0]

                wallet_percentage = wallet[1]

                top_wallets_message += (
                    f"{index}. "
                    f"`{wallet_address}`\n"
                    f"   {wallet_percentage:.2f}%\n"
                )

        else:

            top_wallets_message = (
                "Não foi possível identificar "
                "holders reais."
            )

        # =====================================================
        # 6.6 POOLS IDENTIFICADAS
        # =====================================================

        pool_message = ""

        if liquidity_wallets:

            pool_message = (
                "💧 POOL IDENTIFICADA\n\n"
            )

            for pool_address, pool_percent in (
                liquidity_wallets.items()
            ):

                pool_message += (
                    f"Pool: `{pool_address}`\n"
                    f"Tokens na pool: "
                    f"{pool_percent:.2f}%\n\n"
                )

        else:

            pool_message = (
                "💧 POOL IDENTIFICADA\n\n"
                "Não foi possível confirmar a pool "
                "entre as maiores token accounts.\n\n"
            )

        # =====================================================
        # 7. CLASSIFICAÇÃO BRUTA
        # =====================================================

        if top_10_percentage >= 70:

            raw_concentration_status = (
                "🔴 MUITO ALTA"
            )

        elif top_10_percentage >= 50:

            raw_concentration_status = (
                "🟠 ALTA"
            )

        elif top_10_percentage >= 30:

            raw_concentration_status = (
                "🟡 MODERADA"
            )

        else:

            raw_concentration_status = (
                "🟢 BAIXA"
            )

        # =====================================================
        # 8. CLASSIFICAÇÃO REAL
        # =====================================================

        if real_holder_percentage >= 70:

            real_concentration_status = (
                "🔴 MUITO ALTA"
            )

        elif real_holder_percentage >= 50:

            real_concentration_status = (
                "🟠 ALTA"
            )

        elif real_holder_percentage >= 30:

            real_concentration_status = (
                "🟡 MODERADA"
            )

        else:

            real_concentration_status = (
                "🟢 BAIXA"
            )

        # =====================================================
        # 9. CLASSIFICAÇÃO DA LIQUIDEZ
        # =====================================================

        if liquidity >= 50000:

            liquidity_status = (
                "🟢 BOA"
            )

        elif liquidity >= 15000:

            liquidity_status = (
                "🟡 MODERADA"
            )

        elif liquidity >= 5000:

            liquidity_status = (
                "🟠 BAIXA"
            )

        else:

            liquidity_status = (
                "🔴 MUITO BAIXA"
            )

        # =====================================================
        # 10. MENSAGEM DE LIQUIDEZ
        # =====================================================

        liquidity_message = (
            "💧 LIQUIDEZ\n"

            f"Liquidez: "
            f"${liquidity:,.0f}\n"

            f"Market Cap: "
            f"${market_cap:,.0f}\n"

            f"Volume 24h: "
            f"${volume_24h:,.0f}\n"

            f"Variação 24h: "
            f"{price_change:.2f}%\n\n"

            f"Liquidez: "
            f"{liquidity_status}\n"

            f"DEX: {dex_id}\n"

            f"Pool: `{pair_address}`"
        )

        # =====================================================
        # 11. AVISO DE CONCENTRAÇÃO
        # =====================================================

        concentration_warning = ""

        if pool_percentage > 0:

            concentration_warning = (
                "ℹ️ A concentração bruta inclui "
                "tokens identificados na pool.\n"
                "A concentração real abaixo exclui "
                "a pool identificada.\n"
            )

        else:

            concentration_warning = (
                "⚠️ Nenhuma pool foi confirmada "
                "entre as maiores contas analisadas.\n"
            )

        # =====================================================
        # 12. MONTAR RESPOSTA
        # =====================================================

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

            "👥 HOLDER INTELLIGENCE\n\n"

            f"Token accounts analisadas: "
            f"{len(largest_accounts)}\n"

            f"Top 10 bruto: "
            f"{top_10_percentage:.2f}%\n"

            f"Concentração bruta: "
            f"{raw_concentration_status}\n\n"

            f"Owners reais identificados: "
            f"{unique_wallets}\n"

            f"Concentração real: "
            f"{real_holder_percentage:.2f}%\n"

            f"Status real: "
            f"{real_concentration_status}\n\n"

            f"{concentration_warning}\n"

            f"{pool_message}"

            "👛 PRINCIPAIS HOLDERS REAIS\n\n"

            f"{top_wallets_message}\n"

            f"{liquidity_message}\n\n"

            "📊 PRÓXIMAS ANÁLISES\n\n"

            "• Carteira do dev\n"
            "• Histórico on-chain\n"
            "• Relação entre carteiras\n"
            "• Liquidez e pool\n"
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


# =========================================================
# INICIALIZAÇÃO DO BOT
# =========================================================

def main():

    application = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    application.add_handler(
        CommandHandler(
            "top",
            top
        )
    )

    application.add_handler(
        CommandHandler(
            "security",
            security
        )
    )

    print(
        "🤖 Meme Radar AI iniciado."
    )

    application.run_polling()


if __name__ == "__main__":
    main()
