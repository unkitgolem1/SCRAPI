import requests
from bs4 import BeautifulSoup
import sqlite3
import time
from datetime import datetime
import re
import os

class BookExtractor:
    def __init__(self, db_name='libros_clasicos.db'):
        """
        Inicializa el extractor de libros.
        Args:
            db_name (str): Nombre o ruta de la base de datos SQLite
        """
        self.base_url = "https://www.gutenberg.org"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        self.db_name = db_name
        
        # Crear el directorio para la base de datos si no existe
        os.makedirs(os.path.dirname(os.path.abspath(db_name)), exist_ok=True)
        
        self.setup_database()
    
    def setup_database(self):
        """Configura la base de datos SQLite"""
        try:
            self.conn = sqlite3.connect(self.db_name)
            self.cur = self.conn.cursor()
            
            # Crear tablas si no existen
            self.cur.execute('''
                CREATE TABLE IF NOT EXISTS libros (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    titulo TEXT NOT NULL,
                    autor TEXT,
                    fecha_extraccion DATETIME,
                    url_origen TEXT,
                    UNIQUE(url_origen)
                )
            ''')
            
            self.cur.execute('''
                CREATE TABLE IF NOT EXISTS capitulos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    libro_id INTEGER,
                    numero INTEGER,
                    titulo TEXT,
                    contenido TEXT,
                    FOREIGN KEY (libro_id) REFERENCES libros (id),
                    UNIQUE(libro_id, numero)
                )
            ''')
            
            self.conn.commit()
            print(f"Base de datos '{self.db_name}' configurada exitosamente")
        except sqlite3.Error as e:
            print(f"Error configurando la base de datos: {e}")
            raise

    def clean_text(self, text):
        """Limpia el texto eliminando espacios extras y caracteres no deseados"""
        if not text:
            return ""
        # Elimina múltiples espacios en blanco
        text = re.sub(r'\s+', ' ', text)
        # Elimina caracteres especiales manteniendo puntuación básica
        text = re.sub(r'[^\w\s.,!?¡¿:;()\-"""\'áéíóúÁÉÍÓÚñÑ]+', '', text)
        return text.strip()

    def extract_chapters(self, html_content):
        """Extrae capítulos del contenido HTML"""
        if not html_content:
            return []
            
        soup = BeautifulSoup(html_content, 'html.parser')
        chapters = []
        
        # Busca elementos que puedan ser capítulos
        chapter_patterns = r'cap[ií]tulo|[IVX]+\.|\d+\.|parte|libro'
        chapter_markers = soup.find_all(['h1', 'h2', 'h3', 'div', 'p'], 
                                      string=re.compile(chapter_patterns, re.I))
        
        if not chapter_markers:
            # Si no encuentra capítulos, trata todo como un solo capítulo
            content = [p.get_text() for p in soup.find_all('p') if p.get_text().strip()]
            if content:
                chapters.append({
                    'numero': 1,
                    'titulo': 'Texto completo',
                    'contenido': '\n\n'.join(map(self.clean_text, content))
                })
            return chapters
        
        for i, marker in enumerate(chapter_markers):
            chapter_title = self.clean_text(marker.get_text())
            chapter_content = []
            
            # Obtiene todo el contenido hasta el siguiente capítulo
            current = marker.find_next()
            while current and current != chapter_markers[i+1] if i+1 < len(chapter_markers) else None:
                if current.name == 'p':
                    text = self.clean_text(current.get_text())
                    if text and len(text) > 50:  # Solo añade párrafos significativos
                        chapter_content.append(text)
                current = current.find_next()
            
            if chapter_content:  # Solo añade capítulos con contenido
                chapters.append({
                    'numero': i + 1,
                    'titulo': chapter_title,
                    'contenido': '\n\n'.join(chapter_content)
                })
        
        return chapters

    def save_to_database(self, title, author, url, chapters):
        """Guarda el libro y sus capítulos en la base de datos"""
        try:
            # Verifica si el libro ya existe
            self.cur.execute('SELECT id FROM libros WHERE url_origen = ?', (url,))
            existing_book = self.cur.fetchone()
            
            if existing_book:
                print(f"El libro '{title}' ya existe en la base de datos")
                return False
            
            # Inserta información del libro
            self.cur.execute('''
                INSERT INTO libros (titulo, autor, fecha_extraccion, url_origen)
                VALUES (?, ?, ?, ?)
            ''', (title, author, datetime.now(), url))
            
            libro_id = self.cur.lastrowid
            
            # Inserta los capítulos
            for chapter in chapters:
                self.cur.execute('''
                    INSERT INTO capitulos (libro_id, numero, titulo, contenido)
                    VALUES (?, ?, ?, ?)
                ''', (libro_id, chapter['numero'], chapter['titulo'], chapter['contenido']))
            
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Error guardando en la base de datos: {e}")
            self.conn.rollback()
            return False

    def get_book_content(self, url):
        """Obtiene el contenido de un libro"""
        try:
            time.sleep(2)  # Ser respetuosos con el servidor
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            print(f"Error obteniendo el libro: {e}")
            return None

    def extract_book(self, url, title, author):
        """Proceso completo de extracción de un libro"""
        print(f"Extrayendo libro: {title}")
        
        html_content = self.get_book_content(url)
        if html_content:
            chapters = self.extract_chapters(html_content)
            if chapters:
                success = self.save_to_database(title, author, url, chapters)
                if success:
                    print(f"Libro '{title}' guardado exitosamente con {len(chapters)} capítulos")
                    return True
            else:
                print(f"No se encontraron capítulos en el libro '{title}'")
        return False

    def list_books(self):
        """Lista todos los libros en la base de datos"""
        try:
            self.cur.execute('''
                SELECT id, titulo, autor, fecha_extraccion 
                FROM libros ORDER BY fecha_extraccion DESC
            ''')
            return self.cur.fetchall()
        except sqlite3.Error as e:
            print(f"Error listando libros: {e}")
            return []

    def get_book_chapters(self, libro_id):
        """Obtiene todos los capítulos de un libro"""
        try:
            self.cur.execute('''
                SELECT numero, titulo, contenido 
                FROM capitulos 
                WHERE libro_id = ? 
                ORDER BY numero
            ''', (libro_id,))
            return self.cur.fetchall()
        except sqlite3.Error as e:
            print(f"Error obteniendo capítulos: {e}")
            return []

    def close(self):
        """Cierra la conexión a la base de datos"""
        if hasattr(self, 'conn'):
            self.conn.close()
            print("Conexión a la base de datos cerrada")

# Ejemplo de uso
if __name__ == "__main__":
    try:
        # Crear el extractor
        extractor = BookExtractor()
        
        # URL de ejemplo (Don Quijote en Proyecto Gutenberg)
        url = "https://www.gutenberg.org/files/2000/2000-h/2000-h.htm"
        
        # Extraer el libro
        success = extractor.extract_book(
            url=url,
            title="Don Quijote de la Mancha",
            author="Miguel de Cervantes"
        )
        
        if success:
            # Mostrar los libros en la base de datos
            print("\nLibros guardados:")
            for libro in extractor.list_books():
                print(f"ID: {libro[0]}, Título: {libro[1]}, Autor: {libro[2]}")
                
                # Mostrar los capítulos del libro
                capitulos = extractor.get_book_chapters(libro[0])
                print(f"Capítulos encontrados: {len(capitulos)}")
                for cap_num, cap_titulo, _ in capitulos[:3]:  # Mostrar solo los primeros 3 capítulos
                    print(f"  Capítulo {cap_num}: {cap_titulo}")
    
    except Exception as e:
        print(f"Error durante la ejecución: {e}")
    
    finally:
        # Siempre cerrar la conexión
        extractor.close()