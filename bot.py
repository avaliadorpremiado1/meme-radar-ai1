import os
import requests

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


TOKEN = os.environ["TELEGRAM_TOKEN"]


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
        "🔎 O scanner de oportunidades será ativado nas próximas etapas.\n\n"
        "Por enquanto, use:\n"
        "/analyze ENDERECO_DO_TOKEN"
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


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🤖 COMANDOS DO MEME RADAR AI\n\n"
        "/start — Iniciar\n"
        "/top — Oportunidades\n"
        "/analyze — Analisar token\n"
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
        CommandHandler("help", help_command)
    )

    print("🤖 Meme Radar AI iniciado!")

    app.run_polling()


if __name__ == "__main__":
    main()
