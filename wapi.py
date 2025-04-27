import requests
import json
import sys
import urllib.parse
import re

class WikipediaAPI:
    def __init__(self, language="tr"):
        """
        Wikipedia API istemcisi
        :param language: Dil kodu (örn: tr, en, de, fr)
        """
        self.language = language
        self.base_url = f"https://{language}.wikipedia.org/w/api.php"
        self.wiki_url = f"https://{language}.wikipedia.org/wiki/"
    
    def search(self, query, limit=10):
        """
        Wikipedia'da arama yapar
        :param query: Arama sorgusu
        :param limit: Sonuç sayısı sınırı
        :return: Arama sonuçları listesi
        """
        params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "utf8": 1
        }
        
        response = requests.get(self.base_url, params=params)
        data = response.json()
        
        if "query" in data and "search" in data["query"]:
            return data["query"]["search"]
        return []
    
    def get_page_content(self, page_id):
        """
        Sayfa ID'sine göre tam içerik alır
        :param page_id: Wikipedia sayfa ID'si
        :return: Sayfa içeriği
        """
        # İlk olarak, standart içeriği almaya çalışalım
        params = {
            "action": "query",
            "format": "json",
            "prop": "extracts",
            "pageids": page_id,
            "explaintext": 1,
            "exintro": 0    # 0: tam içerik, 1: sadece giriş bölümü
        }
        
        response = requests.get(self.base_url, params=params)
        data = response.json()
        
        content = ""
        if "query" in data and "pages" in data["query"]:
            page_data = data["query"]["pages"].get(str(page_id))
            if page_data and "extract" in page_data:
                content = page_data["extract"]
        
        # Eğer içerik kısaysa veya yoksa, bölümleri ayrı ayrı almayı deneyelim
        if not content or len(content) < 1000:
            # Önce sayfa başlığını alalım
            params = {
                "action": "query",
                "format": "json",
                "prop": "info",
                "pageids": page_id,
                "inprop": "url|displaytitle"
            }
            
            response = requests.get(self.base_url, params=params)
            data = response.json()
            
            page_title = ""
            if "query" in data and "pages" in data["query"]:
                page_data = data["query"]["pages"].get(str(page_id))
                if page_data and "title" in page_data:
                    page_title = page_data["title"]
            
            if page_title:
                # Şimdi sayfa bölümlerini alalım
                content = self.get_full_content_by_title(page_title)
        
        return content
    
    def get_full_content_by_title(self, title):
        """
        Başlığa göre tam içerik alır ve bölümleri birleştirir
        :param title: Sayfa başlığı
        :return: Tam sayfa içeriği
        """
        # Önce bölüm yapısını alalım
        params = {
            "action": "parse",
            "format": "json",
            "page": title,
            "prop": "sections"
        }
        
        response = requests.get(self.base_url, params=params)
        data = response.json()
        
        full_content = f"# {title}\n\n"
        
        # Ana içeriği alalım (giriş bölümü)
        params = {
            "action": "parse",
            "format": "json",
            "page": title,
            "prop": "text",
            "section": 0,
            "formatversion": 2
        }
        
        response = requests.get(self.base_url, params=params)
        try:
            data = response.json()
            if "parse" in data and "text" in data["parse"]:
                # HTML içeriğini düz metne çevirme girişimi
                content = data["parse"]["text"]
                # HTML etiketlerini kaldırma girişimi
                content = self.html_to_text(content)
                full_content += content + "\n\n"
        except Exception as e:
            full_content += f"Giriş bölümü alınamadı: {str(e)}\n\n"
        
        # Bölümleri alalım
        params = {
            "action": "parse",
            "format": "json",
            "page": title,
            "prop": "sections"
        }
        
        response = requests.get(self.base_url, params=params)
        try:
            data = response.json()
            if "parse" in data and "sections" in data["parse"]:
                for section in data["parse"]["sections"]:
                    section_index = section.get("index", "0")
                    section_title = section.get("line", "")
                    
                    # Referans, Kaynakça gibi bölümleri atlayalım
                    if any(skip_word in section_title.lower() for skip_word in ["kaynakça", "referans", "dipnot", "dış bağlantı", "ayrıca bakınız"]):
                        continue
                    
                    # Her bölümü ayrı ayrı alalım
                    params = {
                        "action": "parse",
                        "format": "json",
                        "page": title,
                        "prop": "text",
                        "section": section_index,
                        "formatversion": 2
                    }
                    
                    section_response = requests.get(self.base_url, params=params)
                    try:
                        section_data = section_response.json()
                        if "parse" in section_data and "text" in section_data["parse"]:
                            section_content = section_data["parse"]["text"]
                            # HTML etiketlerini kaldırma girişimi
                            section_content = self.html_to_text(section_content)
                            
                            if section_content.strip():  # Boş bölümleri atlayalım
                                full_content += f"## {section_title}\n\n{section_content}\n\n"
                    except Exception as e:
                        continue
        except Exception as e:
            full_content += f"Bölümler alınamadı: {str(e)}\n\n"
        
        # Alternatif yöntem: Mobil API kullanarak düz metin almak
        if len(full_content) < 1000:
            try:
                mobile_url = f"https://{self.language}.wikipedia.org/api/rest_v1/page/mobile-sections/{urllib.parse.quote(title)}"
                response = requests.get(mobile_url)
                data = response.json()
                
                # Giriş bölümü
                if "lead" in data and "sections" in data["lead"]:
                    for section in data["lead"]["sections"]:
                        if "text" in section:
                            section_text = self.html_to_text(section["text"])
                            full_content += section_text + "\n\n"
                
                # Diğer bölümler
                if "remaining" in data and "sections" in data["remaining"]:
                    for section in data["remaining"]["sections"]:
                        # Referans, Kaynakça gibi bölümleri atlayalım
                        if "line" in section and any(skip_word in section["line"].lower() for skip_word in ["kaynakça", "referans", "dipnot", "dış bağlantı", "ayrıca bakınız"]):
                            continue
                            
                        if "line" in section:
                            full_content += f"## {section['line']}\n\n"
                        if "text" in section:
                            section_text = self.html_to_text(section["text"])
                            if section_text.strip():  # Boş bölümleri atlayalım
                                full_content += section_text + "\n\n"
            except Exception as e:
                full_content += f"Mobil API üzerinden içerik alınamadı: {str(e)}\n\n"
        
        # Son temizleme
        full_content = self.clean_wiki_content(full_content)
                
        return full_content
    
    def html_to_text(self, html_content):
        """
        HTML içeriğini basit düz metne dönüştürür
        """
        # CSS içeriklerini temizle
        html_content = re.sub(r'<style[^>]*>.*?</style>', ' ', html_content, flags=re.DOTALL)
        
        # CSS sınıf tanımlamalarını temizle
        html_content = re.sub(r'\.mw-parser-output\s+\.[^{]+\{[^}]+\}', ' ', html_content)
        
        # HTML etiketlerini kaldır
        text = re.sub(r'<[^>]+>', ' ', html_content)
        
        # Fazla boşlukları temizle
        text = re.sub(r'\s+', ' ', text)
        
        # HTML karakter kodlarını çöz
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&amp;', '&')
        text = text.replace('&quot;', '"')
        text = text.replace('&apos;', "'")
        
        return text.strip()
    
    def clean_wiki_content(self, content):
        """
        Wikipedia içeriğinden gereksiz metinleri temizler
        """
        # [değiştir | kaynağı değiştir] tarzı metinleri temizle
        content = re.sub(r'\[\s*değiştir\s*\|\s*kaynağı\s*değiştir\s*\]', '', content)
        content = re.sub(r'\[\s*edit\s*\|\s*edit source\s*\]', '', content)
        
        # İçerik düzenleme bağlantılarını temizle
        content = re.sub(r'\(\s*[Dd]üzenle\s*\)', '', content)
        content = re.sub(r'\(\s*[Ee]dit\s*\)', '', content)
        
        # CSS sınıf tanımlarını temizle
        content = re.sub(r'\.mw-parser-output\s+\.[^{]+\{[^}]+\}', '', content)
        
        # Dosya ve medya referanslarını temizle
        content = re.sub(r'Dosya:[^\]]+\]', '', content)
        content = re.sub(r'File:[^\]]+\]', '', content)
        content = re.sub(r'Media:[^\]]+\]', '', content)
        
        # Sayfa referanslarını temizle
        content = re.sub(r'\[\d+\]', '', content)
        
        # Fazla boş satırları temizle
        content = re.sub(r'\n{3,}', '\n\n', content)
        
        return content
    
    def get_page_images(self, page_id):
        """
        Sayfa ID'sine göre resimleri alır
        :param page_id: Wikipedia sayfa ID'si
        :return: Sayfa resimlerinin listesi
        """
        params = {
            "action": "query",
            "format": "json",
            "prop": "images",
            "pageids": page_id
        }
        
        response = requests.get(self.base_url, params=params)
        data = response.json()
        
        if "query" in data and "pages" in data["query"]:
            page_data = data["query"]["pages"].get(str(page_id))
            if page_data and "images" in page_data:
                return [img["title"] for img in page_data["images"]]
        return []
    
    def get_image_url(self, image_title):
        """
        Resim başlığına göre resim URL'sini alır
        :param image_title: Resim başlığı (File:örnek.jpg gibi)
        :return: Resim URL'si
        """
        # Dosya başlığından "File:" önekini kaldır
        image_name = image_title.replace("File:", "").replace("Dosya:", "")
        
        params = {
            "action": "query",
            "format": "json",
            "prop": "imageinfo",
            "titles": image_title,
            "iiprop": "url"
        }
        
        response = requests.get(self.base_url, params=params)
        data = response.json()
        
        if "query" in data and "pages" in data["query"]:
            for page_id, page_data in data["query"]["pages"].items():
                if "imageinfo" in page_data and len(page_data["imageinfo"]) > 0:
                    return page_data["imageinfo"][0]["url"]
        return None
    
    def get_page_categories(self, page_id):
        """
        Sayfa ID'sine göre kategorileri alır
        :param page_id: Wikipedia sayfa ID'si
        :return: Kategori listesi
        """
        params = {
            "action": "query",
            "format": "json",
            "prop": "categories",
            "pageids": page_id,
            "cllimit": 50
        }
        
        response = requests.get(self.base_url, params=params)
        data = response.json()
        
        categories = []
        if "query" in data and "pages" in data["query"]:
            page_data = data["query"]["pages"].get(str(page_id))
            if page_data and "categories" in page_data:
                categories = [cat["title"].replace("Kategori:", "").replace("Category:", "") 
                             for cat in page_data["categories"]]
        return categories
    
    def get_page_url(self, title):
        """
        Sayfa başlığından URL oluşturur
        :param title: Sayfa başlığı
        :return: Wikipedia URL'si
        """
        # URL için başlığı kodla
        encoded_title = urllib.parse.quote(title.replace(" ", "_"))
        return f"{self.wiki_url}{encoded_title}"

    def save_results_to_file(self, search_term, results, output_file="wikipedia_results.txt"):
        """
        Arama sonuçlarını ve içeriği dosyaya kaydeder
        :param search_term: Arama terimi
        :param results: Arama sonuçları
        :param output_file: Çıktı dosyası adı
        """
        with open(output_file, "w", encoding="utf-8") as file:
            file.write(f"ARAMA TERİMİ: {search_term}\n")
            file.write("=" * 50 + "\n\n")
            
            if not results:
                file.write("Sonuç bulunamadı.\n")
                return
            
            file.write(f"{len(results)} SONUÇ BULUNDU:\n\n")
            
            for i, result in enumerate(results):
                file.write(f"SONUÇ {i+1}:\n")
                file.write(f"Başlık: {result['title']}\n")
                file.write(f"Sayfa ID: {result['pageid']}\n")
                
                # Sayfa URL'si ekle
                page_url = self.get_page_url(result['title'])
                file.write(f"Sayfa URL: {page_url}\n\n")
                
                # Kategorileri al
                categories = self.get_page_categories(result['pageid'])
                if categories:
                    file.write("KATEGORİLER:\n")
                    file.write(", ".join(categories[:10]))  # İlk 10 kategori
                    file.write("\n\n")
                
                # İçeriği al (genişletilmiş)
                print(f"'{result['title']}' için içerik alınıyor...")
                content = self.get_page_content(result['pageid'])
                if content:
                    file.write("İÇERİK:\n")
                    file.write(content)
                    file.write("\n\n")
                else:
                    file.write("İçerik bulunamadı.\n\n")
                
                # Resimleri al
                images = self.get_page_images(result['pageid'])
                if images:
                    file.write("RESİMLER:\n")
                    for j, img in enumerate(images[:5]):  # İlk 5 resmi kaydet
                        img_url = self.get_image_url(img)
                        file.write(f"{j+1}. {img}\n")
                        if img_url:
                            file.write(f"   URL: {img_url}\n")
                    file.write("\n")
                
                file.write("-" * 50 + "\n\n")


def main():
    if len(sys.argv) < 2:
        print("Kullanım: python3 wapi.py <arama_terimi> [dil_kodu] [çıktı_dosyası]")
        print("Örnek: python3 wapi.py 'İstanbul' tr istanbul_bilgisi.txt")
        return
    
    search_term = sys.argv[1]
    # Limit değeri artık sabit 5 olarak ayarlandı
    limit = 1   
    # Komut satırı argümanlarının indeksleri değiştirildi
    language = sys.argv[2] if len(sys.argv) > 2 else "tr"
    output_file = sys.argv[3] if len(sys.argv) > 3 else "wikipedia_results.txt"
    
    print(f"'{search_term}' için Wikipedia'da arama yapılıyor...")
    wiki_api = WikipediaAPI(language=language)
    
    results = wiki_api.search(search_term, limit=limit)
    
    if results:
        print(f"{len(results)} sonuç bulundu.")
        wiki_api.save_results_to_file(search_term, results, output_file)
        print(f"Sonuçlar '{output_file}' dosyasına kaydedildi.")
    else:
        print("Sonuç bulunamadı.")
        with open(output_file, "w", encoding="utf-8") as file:
            file.write(f"ARAMA TERİMİ: {search_term}\n")
            file.write("=" * 50 + "\n\n")
            file.write("Sonuç bulunamadı.\n")


if __name__ == "__main__":
    main()