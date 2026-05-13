@echo off
:: One-command launcher: SSH into the GCP VM and open the PawPoller CLI
:: menu directly. The -t flag forces a TTY so Rich's menus and prompts
:: render properly over SSH; sudo -u kithetiger switches to the user
:: that owns the CLI config and the data directory.
gcloud compute ssh pawpoller --zone=us-east1-c --ssh-flag="-t" --command="sudo -u kithetiger -i /home/kithetiger/PawPoller/cli/pp.sh"
