from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import requests
from PIL import Image
from bs4 import BeautifulSoup
from ebooklib import epub
import uuid
import os, shutil
import calendar


def clear_tmp_dir():
    shutil.rmtree('tmp', ignore_errors=True)
    os.makedirs('tmp')


def title_to_filename(title):
    return ''.join(e for e in title if e.isalnum()).lower()


def extract_sequence_links(html):
    soup = BeautifulSoup(html, 'html.parser')
    links = soup.find_all('a', href=True)
    return [link["href"] for link in links if '/s/' in link["href"] and '/p/' not in link["href"]]


def get_unique_sequence_links(files):
    sequence_links = []
    for file in files:
        with open(file, 'r') as html_file:
            html = html_file.read()
            sequence_links += extract_sequence_links(html)
    return list(set(sequence_links))


def download_and_convert_image(image_link, file_name):
    if image_link[0] == '/':
        image_link = 'https://www.lesswrong.com' + image_link

    # find the file extension
    extension = image_link.split('?')[0].split('.')[-1]

    if extension not in ['jpg', 'png', 'jpeg', 'svg', 'PNG']:
        extension = ''

    img_data = requests.get(image_link)
    image_path = 'tmp/' + file_name + '.' + extension
    with open(image_path, 'wb') as f:
        f.write(img_data.content)

    # Convert the image to PNG
    with Image.open(image_path) as im:
        width, height = im.size
        new_width = 768
        new_height = int(new_width * height / width)
        im = im.resize((new_width, new_height))
        im.save('tmp/' + file_name + '.png', 'png')


def extract_details_from_sequence_link(link):
    # Set up the Chrome options
    chrome_options = Options()
    chrome_options.add_argument("--headless")

    # Set up the webdriver
    driver = webdriver.Chrome(options=chrome_options)

    try:
        # Navigate to the website
        driver.get(link)
        # Wait for the page to load
        driver.implicitly_wait(10)
        title = driver.find_element(By.CSS_SELECTOR, "h1").text
        computer_title = title_to_filename(title)
    except Exception as e:
        print(f"Error in retrieving Sequence {link}: {e}")

    try:
        author = driver.find_element(By.CSS_SELECTOR, "a.UsersNameDisplay-userName").text
    except Exception as e:
        print(f"Error in retrieving author from Sequence {link}: {e}")
        author = "Unknown"

    # Find all the links on the page
    links = driver.find_elements(By.CSS_SELECTOR, "a")

    # Get the cover image
    try:
        image_url = driver.find_element(By.CSS_SELECTOR, "img").get_attribute('src')
        download_and_convert_image(image_url, computer_title)
        cover_image_path = f'tmp/{computer_title}.png'
    except Exception as e:
        print(f"Error in retrieving cover image from Sequence {link}: {e}")
        cover_image_path = 'lw_cover.svg'

    # Filter the links to keep only those containing "/p/ and lesswrong"
    post_links = [link.get_attribute("href") for link in links if '/p/' in link.get_attribute("href") and
                  'lesswrong' in link.get_attribute("href")]

    return title, author, cover_image_path, post_links


def initialize_book(title, author, cover_image_path):
    book = epub.EpubBook()
    book.set_identifier(f'{uuid.uuid4().hex}')
    book.set_title(title)
    book.add_author(author)
    book.set_language('en')
    book.set_cover(cover_image_path, open(cover_image_path, 'rb').read())
    return book


def add_chapter(book, post_link):
    print(book.title, post_link)
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    driver = webdriver.Chrome(options=chrome_options)
    try:
        driver.get(post_link)
        driver.implicitly_wait(10)
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')

        for tag in soup.find_all("div", {'class': 'SideCommentIcon-sideCommentIconWrapper'}):
            tag.decompose()
        post_content_div = soup.find('div', {'class': 'PostsPage-postContent'})

        img_tags = post_content_div.find_all('img')
        img_tags = [img for img in img_tags if "MuiSvgIcon-root" not in img.get("class", [])]
        chapter_title = soup.find('a', {'class': 'PostsPageTitle-link'}).get_text()
        for img_counter, img in enumerate(img_tags):
            original_src = img['src']
            file_name = f'{title_to_filename(chapter_title)}_{img_counter}'
            try:
                download_and_convert_image(original_src, file_name)
                img['src'] = file_name
                img['srcset'] = file_name
                img['alt'] = uuid.uuid4().hex
                with open("tmp/" + file_name + '.png', "rb") as f:
                    img_content = f.read()
                epub_img = epub.EpubImage(
                    uid=img['alt'],
                    file_name=file_name,
                    media_type="image/png",
                    content=img_content
                )
                book.add_item(epub_img)
            except Exception as e:
                print("Exception in image", e, original_src)

        text = f"<h1 style='margin: 1rem auto;'>{chapter_title}</h1>" + str(post_content_div)
        chapter = epub.EpubHtml(
            title=chapter_title,
            file_name=f'{uuid.uuid4().hex}.html',
            content=text,
        )
        book.add_item(chapter)

        return book, chapter
    finally:
        driver.quit()


def finalize_book(book, title, toc):
    book.toc = toc
    book.spine = ["nav"] + toc

    # add default NCX and Nav file
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # define CSS style
    style = "BODY {color: white;}"
    nav_css = epub.EpubItem(
        uid="style_nav",
        file_name="style/nav.css",
        media_type="text/css",
        content=style,
    )

    book.add_item(nav_css)

    epub.write_epub(f'output/{title_to_filename(title)}.epub', book)
    clear_tmp_dir()
    return book


def build_book(sequence_link):
    title, author, cover_image_path, post_links = extract_details_from_sequence_link(sequence_link)
    if title_to_filename(title) + '.epub' not in os.listdir('output'):
        book = initialize_book(title, author, cover_image_path)
        toc = []
        for post_link in post_links:
            try:
                book, chapter = add_chapter(book, post_link)
                toc.append(chapter)
            except Exception as e:
                print(f"Exception in {post_link}: {e}")
        finalize_book(book, title, toc)


def build_all_books():
    html_files = ['html_files/library.html', 'html_files/eliezer.html', 'html_files/scott.html', 'html_files/codex.html']
    sequence_links = get_unique_sequence_links(html_files)
    for sequence_link in sequence_links:
        try:
            build_book(sequence_link)
        except Exception as e:
            print(f"Exception in Sequence {sequence_link}: {e}")


def build_best_of_month_book(month, year):
    # Set up the Chrome options
    chrome_options = Options()
    chrome_options.add_argument("--headless")

    # Set up the webdriver
    driver = webdriver.Chrome(options=chrome_options)

    # the month and year are now integers, we need the start date and end date in the format of YYYY-MM-DD
    start_date = f'{year}-{month:02d}-01'
    end_date = f'{year}-{month:02d}-{calendar.monthrange(year, month)[1]}'

    # Set the title of the book
    title = f'Best of LessWrong: {calendar.month_name[month]} {year}'
    author = 'LessWrong'
    cover_image_path = 'lw_cover.svg'

    # Get the right link
    link = f'https://www.lesswrong.com/allPosts?filter=frontpage&after={start_date}&before={end_date}&timeframe=allTime'
    if title_to_filename(title) + '.epub' not in os.listdir('output'):
        try:
            # Navigate to the website
            driver.get(link)

            # Wait for the page to load
            driver.implicitly_wait(10)

            book = initialize_book(title, author, cover_image_path)
            toc = []
            links = driver.find_elements(By.CSS_SELECTOR, "a")
            links = [str(link.get_attribute("href")) for link in links]
            post_links = [link for link in links if 'https://www.lesswrong.com/posts/' in link]

            for post_link in post_links:
                book, chapter = add_chapter(book, post_link)
                toc.append(chapter)
            finalize_book(book, title, toc)
        except Exception as e:
            if 'title' in locals():
                print(f"Exception in {title}: {e}")
            else:
                print(f"Exception {e}")
        finally:
            driver.quit()


def build_best_of_month_books():
    for year in range(2012, 2024):
        for month in range(1, 13):
            build_best_of_month_book(month, year)


def build_readme():
    html_files = ['html_files/library.html', 'html_files/eliezer.html', 'html_files/scott.html', 'html_files/codex.html']
    sequence_links = get_unique_sequence_links(html_files)
    all_titles_and_authors = []
    for sequence_link in sequence_links:
        try:
            title, author, cover_image_path, post_links = extract_details_from_sequence_link(sequence_link)
            print(title, author)
            all_titles_and_authors.append((title, author))
        except Exception as e:
            print(f"Exception in {sequence_link}: {e}")
    sorted_by_title = sorted(all_titles_and_authors, key=lambda x: x[0])
    with open('README.md', 'w') as f:
        f.write('## Sequences\n')
        for title, author in sorted_by_title:
            f.write(f'* [{title}](output/{title_to_filename(title)}.epub) by {author}\n')

        f.write('## Best of LessWrong\n')
        for year in range(2023, 2011, -1):
            for month in range(12, 0, -1):
                file_name = title_to_filename(f'Best of LessWrong: {calendar.month_name[month]} {year}') + '.epub'
                f.write(f'* [Best of LessWrong: {calendar.month_name[month]} {year}](output/{file_name}) by LessWrong\n')


if __name__ == '__main__':
    build_all_books()
    build_best_of_month_books()
    # build_readme()