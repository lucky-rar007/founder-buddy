from ingestion.graph_client import graph_client


class SelectorCLI:
    """
    Interactive CLI for selecting Teams, Channels, and Outlook users.
    """

    # ─────────────────────────────────────────
    # TEAMS
    # ─────────────────────────────────────────

    def select_team(self) -> str:
        teams = graph_client.get_teams()

        if not teams:
            raise Exception("No teams found")

        print("\n=== AVAILABLE TEAMS ===")
        print("  [0] Ingest All Teams")
        for i, team in enumerate(teams):
            print(f"  [{i + 1}] {team.get('displayName')}")

        choice = self._get_choice(len(teams) + 1, "Select Team")
        if choice == 0:
            print("\n  * Team: All Teams\n")
            return "all"

        selected_team = teams[choice - 1]
        print(f"\n  * Team: {selected_team.get('displayName')}\n")
        return selected_team["id"]

    def select_channel(self, team_id: str) -> str:
        channels = graph_client.get_channels(team_id)

        if not channels:
            raise Exception("No channels found")

        print("\n=== AVAILABLE CHANNELS ===")
        print("  [0] Ingest All Channels")
        for i, ch in enumerate(channels):
            print(f"  [{i + 1}] {ch.get('displayName')}")

        choice = self._get_choice(len(channels) + 1, "Select Channel")
        if choice == 0:
            print("\n  * Channel: All Channels\n")
            return "all"

        selected_channel = channels[choice - 1]
        print(f"\n  * Channel: {selected_channel.get('displayName')}\n")
        return selected_channel["id"]

    # ─────────────────────────────────────────
    # OUTLOOK
    # ─────────────────────────────────────────

    def select_user(self) -> tuple[str, str]:
        """
        Fetch all users from Graph API and let the operator pick one.

        Returns:
            (user_id, display_name) tuple
        """
        users = graph_client.get_users()

        if not users:
            raise Exception("No users found in the directory")

        print("\n=== AVAILABLE USERS ===")
        for i, user in enumerate(users):
            display  = user.get("displayName", "—")
            upn      = user.get("userPrincipalName", "")
            label    = f"{display} <{upn}>" if upn else display
            print(f"  [{i}] {label}")

        choice = self._get_choice(len(users), "Select User")
        selected = users[choice]

        # Prioritize userPrincipalName (email) for better readability in filenames and configs
        user_id      = selected.get("userPrincipalName") or selected.get("id") or "me"
        display_name = selected.get("displayName", user_id)

        print(f"\n  * User: {display_name}\n")
        return user_id, display_name

    # ─────────────────────────────────────────
    # SHARED HELPER
    # ─────────────────────────────────────────

    def _get_choice(self, max_len: int, prompt: str) -> int:
        while True:
            try:
                choice = int(input(f"\n{prompt} (0–{max_len - 1}): "))
                if 0 <= choice < max_len:
                    return choice
                print("  Invalid choice — try again.")
            except ValueError:
                print("  Enter a valid number.")
