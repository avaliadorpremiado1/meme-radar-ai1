import os

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


TOKEN = os.environ["TELEGRAM_TOKEN"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 MEME RADAR AI\n\n"
        "Seu radar inteligente de memecoins.\n\n"
        "Comandos disponíveis:\n"
        "/top — Melhores oportunidades\n"
        "/analyze — Analisar uma moeda\n"
        "/status — Status do sistema\n"
        "/help — Ajuda\n\n"
        "⚠️ Sistema em desenvolvimento."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🟢 MEME RADAR AI está online!\n\n"
        "Scanner: 🟡\n"
        "Segurança: 🟡\n"
        "Wallet Intelligence: 🟡\n"
        "IA: 🟡"
    )


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔎 O scanner ainda está sendo configurado.\n\n"
        "Em breve vou procurar oportunidades automaticamente."
    )


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "🔎 Para analisar um token, use:\n\n"
            "/analyze ENDERECO_DO_TOKEN"
        )
        return

    token = context.args[0]

    await update.message.reply_text(
        f"🔎 Token recebido:\n\n{token}\n\n"
        "⏳ O módulo de análise ainda está sendo configurado."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("analyze", analyze))
    app.add_handler(CommandHandler("help", help_command))

    print("🤖 Meme Radar AI iniciado!")

    app.run_polling()


if __name__ == "__main__":
    main()
