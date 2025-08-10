import feedparser
import xml.etree.ElementTree as ET

def get_feeds_from_opml(filename='subscriptions.opml'):
    """从 OPML 文件中解析并返回所有 RSS feed 的 URL。"""
    urls = []
    try:
        tree = ET.parse(filename)
        root = tree.getroot()
        for outline in root.findall('.//outline'):
            if outline.get('type') == 'rss':
                urls.append(outline.get('xmlUrl'))
    except FileNotFoundError:
        print(f"错误：找不到文件 '{filename}'。请确保 OPML 文件与脚本在同一目录下，或提供正确的文件路径。")
    except ET.ParseError:
        print(f"错误：无法解析文件 '{filename}'。请确保它是一个有效的 OPML 文件。")
    return urls

def fetch_and_display_articles(feed_urls):
    """获取并显示每个 feed 中的文章。"""
    if not feed_urls:
        print("没有找到任何订阅源。")
        return

    for url in feed_urls:
        print(f"\n正在从以下订阅源获取文章： {url}")
        feed = feedparser.parse(url)

        # 检查解析是否成功
        if feed.bozo:
            print(f"  -> 警告：解析此订阅源时可能出现问题。Bozo 异常: {feed.bozo_exception}")
            continue

        # 打印订阅源的标题
        print(f"--- {feed.feed.title} ---\n")

        # 遍历并打印每篇文章的标题和链接
        if not feed.entries:
            print("  -> 此订阅源中没有找到任何文章。")
        else:
            for entry in feed.entries[:5]:  # 获取最新的 5 篇文章
                print(f"  标题: {entry.title}")
                print(f"  链接: {entry.link}")
                if 'published' in entry:
                    print(f"  发布日期: {entry.published}")
                print("-" * 20)

if __name__ == '__main__':
    # 从 OPML 文件中获取所有订阅源的 URL
    # 确保您的 OPML 文件名为 'subscriptions.opml' 或相应地修改文件名
    opml_file = 'follow.opml' 
    feed_urls = get_feeds_from_opml(opml_file)

    # 获取并显示文章
    fetch_and_display_articles(feed_urls)