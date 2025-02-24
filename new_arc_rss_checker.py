name: Check RSS and Send to Discord

on:
  schedule:
    - cron: "0 16 * * *"  # Runs daily at 16:00 UTC
  workflow_dispatch:  # Allows manual trigger

jobs:
  rss_to_discord:
    runs-on: ubuntu-latest

    steps:
    - name: Checkout repository
      uses: actions/checkout@v3

    - name: Run RSS Checker
      run: python new_arc_rss_checker.py
      env:
        DISCORD_WEBHOOK: ${{ secrets.DISCORD_WEBHOOK }}
