from tiresias.config import Settings
from tiresias.db import migrate


def main():
    settings=Settings()
    if not settings.database_url:
        raise SystemExit('Set DATABASE_URL before applying application migrations.')
    migrate(settings.database_url)
    print('Application migrations applied.')


if __name__=='__main__':
    main()
