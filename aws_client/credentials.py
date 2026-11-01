from aws_client import session

class AwsCredentials:
    """
    What Google workload identity federation signs in with instead of a stored Google key:
    spreadsheet_client.auth.use_store(..., aws_credentials=AwsCredentials()). Taken from the
    shared session, so it's the same identity that reads the secrets and writes the backups.
    """
    @property
    def region(self) -> str:
        return session.get_session().region_name

    def get(self) -> tuple[str, str, str | None]:
        credentials = session.get_session().get_credentials()
        if credentials is None:
            raise RuntimeError("No AWS credentials found to sign in to Google with")

        # refreshes temporary credentials first if they are about to expire
        frozen = credentials.get_frozen_credentials()
        return frozen.access_key, frozen.secret_key, frozen.token
