from pywikibot import Page

from utils.wiki_utils import s


def purge_all_pages():
    pages = ["Banner List", "Invite", "Characters", "List of Discs"]
    for page in pages:
        p = Page(s, page)
        p.purge()
        print(f"{page} purged.")


if __name__ == '__main__':
    purge_all_pages()
