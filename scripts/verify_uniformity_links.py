from pathlib import Path
import pandas as pd
import shutil

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR/ "data"
FILE_NAME = "links.xlsx"
# FILE_NAME = "master_links.xlsx"
LINKS_PATH = DATA_DIR/ FILE_NAME
df = pd.read_excel(LINKS_PATH)
print("Reading file:",FILE_NAME,"\n")

def uniformity(selectedColumn):
    columnName = selectedColumn.upper()  # create printable column name
    printerString = f"========================{columnName}========================"

    print(printerString)
    print("Total rows:", len(df[selectedColumn]))

    words = (
        df[selectedColumn]
        .dropna()
        .str.split(",")
        .explode()
        .str.strip()
    )

    freq = (
        words.value_counts()
        .sort_index()  # alphabetical sorting
    )

    print(f"Total count of unique {columnName} is: {len(freq)}")
    print("=" * len(printerString))

    # Find longest term for alignment
    max_len = max(len(word) for word in freq.index)

    for word, count in freq.items():
        print(f"{word:.<{max_len + 5}}({count})")

    print("=" * len(printerString))

header = df.columns.drop(["main_link", "duration", "rate"]).tolist()

#chatgpt code
def print_centered_box(title, items):
    terminal_width = shutil.get_terminal_size().columns

    box_width = max(len(title), max(len(item) for item in items)) + 8

    border = "=" * box_width
    title_line = f"| {title.center(box_width - 4)} |"

    print(border.center(terminal_width))
    print(title_line.center(terminal_width))
    print(border.center(terminal_width))

    for item in items:
        line = f"| {item.ljust(box_width - 4)} |"
        print(line.center(terminal_width))

    print(border.center(terminal_width))

    return box_width


menu_items = [
    "1: Flag",
    "2: Studio",
    "3: Stars",
    "4: Core Categories",
    "5: Categories",
    "6: Positions",
    "7: Language",
    "8: General Tags",
    "9: Website",
    "10: Exit"
]

while True:
    box_width = print_centered_box("Verify Uniformity of Data", menu_items)

    terminal_width = shutil.get_terminal_size().columns
    left_padding = (terminal_width - box_width) // 2

    choice = int(input(" " * left_padding + "Enter Choice: "))

    match choice:
        case 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9:
            uniformity(header[choice - 1])
        case 10:
            print("Exiting.....")
            break
        case _:
            print("Invalid Choice")