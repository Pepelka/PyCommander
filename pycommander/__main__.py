"""python -m pycommander entry point."""
from pycommander.app import TotalCommanderApp


def main():
    app = TotalCommanderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
