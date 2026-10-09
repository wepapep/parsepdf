import pdf_reader

DEFAULT_PATH = "pdfy"
DEFAULT_FILE = "wyniki.csv"
DEFAULT_MODE = "w"
DEFAULT_TECH = "n"
DEFAULT_TECH_FILE = "dane_techniczne.csv"

print("odczyt wynikow badan olejowych")
print("program obsluguje obecnie tylko wyniki z ecola")
print("domyslna wartosc jest w nawiasach kwadratowych []. jesli jest ok to wystarczy enter")
print()
path_to_files = input(f'wskaz folder w ktorym sa raporty [{DEFAULT_PATH}]: ')
if path_to_files == "": path_to_files = DEFAULT_PATH


outputfile = input(f'podaj nazwe pliku csv gdzie maja byc zapisane wyniki [{DEFAULT_FILE}: ')
if outputfile == "": outputfile = DEFAULT_FILE
print("wybierz tryb")
print("w\tnadpisz. obecne dane w pliku znikna")
print("a\tdopisz.  obecne dane w pliku zostana")
writemode = input(f'tryb [{DEFAULT_MODE}]: ')
if writemode == "": writemode = DEFAULT_MODE

techdataread = input(f'czy zapisac tez dane nt urzadzen? y/n [{DEFAULT_TECH}]: ')
if techdataread == "": techdataread = DEFAULT_TECH
techdataread = techdataread == "y"

techfile = None
if techdataread:
	techfile = input(f'podaj nazw pliku do zapisania danych nt urzadzen [{DEFAULT_TECH_FILE}]: ')
	if techfile == "": techfile = DEFAULT_TECH_FILE


print(path_to_files)
print(outputfile)
print(writemode)
print(techdataread)
print(techfile)

print("otwieranie plikow...")
OilData = pdf_reader.bulk_read(path_to_files,"ecol",techdataread)
print("odczytano pliki. zapisywanie...")
pdf_reader.bulk_save(outputfile,writemode,OilData["lab"])
print("zapisano wyniki laboratoryjne")
if techdataread:
	print("zapisywanie danych technicznych")
	pdf_reader.bulk_save(techfile,writemode,OilData["transformers"],pdf_reader.DefaultColumnsTRANSFORMERS)
	print("zapisano dane techniczne")
print("koniec")
print("ctrl-C lub zamknij okno zeby zakonczyc")
input();
