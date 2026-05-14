import asyncio
import nest_asyncio

from github_autosync import startup_pull, start_background_autosync
import rmxbotai


if __name__ == "__main__":
    nest_asyncio.apply()

    # Restore latest sessions/config/logs from GitHub
    startup_pull()

    # Start automatic background GitHub sync
    start_background_autosync()

    # Run original bot
    asyncio.get_event_loop().run_until_complete(rmxbotai.main())
