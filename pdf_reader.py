from pdf_parser import parse_pdf
import os
import re

UnitlessRowCount = 7
UnitlessRowsRange = range(0,UnitlessRowCount+1)

RequiredGeneralFields = ('Numer fabryczny','Lokalizacja','Data przyjęcia próbki','Cel badania')

DefaultColumnsLAB = ['laboratorium','werdykt', 'nastepny termin', 'ocena wizualna', 'Badanie gazów rozpuszczonych w oleju','Badanie właściwości fizykochemicznych','wnioski', 'Numer fabryczny', 'Lokalizacja', 'Data przyjęcia próbki', 'Cel badania', 'WYNIKI ANALIZ', 'Nr lab. próbki:', 'Data zakończenia badań', 'Data poboru próbki *', 'Data wymiany oleju *', 'Temperatura oleju przy poborze * °C', 'Czas pracy urządzenia od wymiany oleju * [h]', 'Całkowity czas pracy urządzenia * [h]', 'Wodór H2', 'Metan CH4', 'Etan C2H6', 'Etylen C2H4', 'Acetylen C2H2', 'Propan C3H8', 'Propylen C3H6', 'Tlenek węgla CO', 'Dwutlenek węgla CO2', 'Tlen O2', 'Azot N2', 'Suma gazów palnych (TDCG)', 'Suma gazów rozpuszczonych (TDG)', 'C2H2/C2H4', 'CH4/H2', 'C2H4/C2H6', 'C2H2/CH4', 'C2H6/C2H2', 'CO2/CO', 'Trójkąt Duvala %CH4', 'Trójkąt Duvala %C2H2', 'Trójkąt Duvala %C2H4', 'Barwa ASTM', 'Ocena wizualna', 'Zawartość wody met. K.F. T', 'Skorygowana zawartość wody na 20°C', 'Napięcie przebicia', 'Odchylenie standardowe napięcia przebicia', 'Rezystywność w 90 °C', 'Współczynnik strat dielektrycznych w 90 °C', 'Liczba kwasowa T', '2 FAL', '5 HMF', '2 FOL', '2 ACF', '5 MEF']
DefaultColumnsTRANSFORMERS = ['Urządzenie', 'Grupa / kategoria', 'Typ urządzenia', 'Producent', 'Numer fabryczny', 'Rok produkcji', 'Zastosowanie', 'Lokalizacja', 'Właściciel', 'Moc [kVA/kvar]', 'Napięcie GN [kV]', 'Napięcie DN [kV]', 'Chłodzenie', 'Budowa', 'Konserwator', 'Regulacja Beznapięciowy przełącznik zaczepów napięcia', 'Ilość oleju [kg]', 'Data przyjęcia próbki', 'Stan próbki', 'Próbkę pobrał', 'Próbkę dostarczył', 'Przedmiot badań', 'Cel badania', 'Metoda i miejsce poboru Kadź transformatora - dół próbki', 'Nazwa oleju']


grade_patterns = dict()
#grade_patterns["ocena wizualna"] = r"(\d?[.|)])?Ocena wizualna(.)*próbki:\s"
#grade_patterns["Badanie gazów rozpuszczonych w oleju"] = r"(\d?[.|)])?\sBadanie gazów rozpuszczonych w oleju.*:\s"
#grade_patterns["Badanie właściwości fizykochemicznych"] = r"(\d?[.|)])?\sBadanie właściwości fizykochemicznych oleju:\s"
#grade_patterns["wnioski"] = r"(\d?[.|)])?\s(Zalecenia|Wnioski)(.)*(wnioski|zalecenia):\s"

NUM = r"(?:\d+\s*[.)]\s*)?"      # optional "1)" or "1." before the header
END = r"[^:.]{0,40}:\s*"         # rest of the header, up to its own colon

grade_patterns = {}
grade_patterns["ocena wizualna"] = NUM + r"Ocena\s+wizualna" + END
grade_patterns["Badanie gazów rozpuszczonych w oleju"] = NUM + r"Badanie\s+gazów\s+rozpuszczonych\s+w\s+oleju" + END
grade_patterns["Badanie właściwości fizykochemicznych"] = NUM + r"Badanie\s+właściwości\s+fizykochemicznych" + END
grade_patterns["wnioski"] = NUM + r"(?:Zalecenia|Wnioski)" + END

#ai-generated
def split_sections(text, patterns, flags=re.IGNORECASE):
    """Split text into {key: content} using one header regex per key."""
    result = dict.fromkeys(patterns)          # every key present, None if not found
    found = []
    for key, pattern in patterns.items():
        if isinstance(pattern, str):          # compiled patterns keep their own flags
            pattern = re.compile(pattern, flags)
        match = pattern.search(text)
        if match:
            found.append((match.start(), match.end(), key))
    found.sort()
    for i, (_, end, key) in enumerate(found):
        stop = found[i + 1][0] if i + 1 < len(found) else len(text)
        result[key] = text[end:stop].strip()
    return result



def extract_data(laboratory,filename_with_path,save_transformer_details,verbose=False):
	if laboratory == "ecol":
		extracted_data = extract_data_ecol(filename_with_path)
		
	LabResultsData = extracted_data["LabResults"]
	GeneralData = dict()
	if save_transformer_details:
		GeneralData = extracted_data["General"]
	return LabResultsData, GeneralData

def extract_data_ecol(filename):
	data = parse_pdf(filename)
	
	fields = dict()
	fields["General"] = dict()
	fields["LabResults"] = dict()
	fields["LabResults"]["laboratorium"] = "Ecol"
	fields["LabResults"]["werdykt"] = data.pop(0)[0]
	#print("verdict  ",fields["LabResults"]["verdict"]);
	fields["LabResults"]["nastepny termin"] = data.pop(0)[0].split(":")[1]
	#print("next_date ",fields["LabResults"]["next_date"]);
	
	general_info = [d for d in data if len(d) == 1]
	
	grade = general_info.pop(-1)[0]
	#print(grade)
	split_grade = split_sections(grade, grade_patterns)
	
	for g in split_grade:
		#print(g)
		#print(split_grade[g]);
		#print()
		fields["LabResults"][g] = split_grade[g]
	
	#print(split_grade)
	#input()
	
	#
	#input()
	
	
	lab_results = [d for d in data if len(d) > 1]
	#print(len(general_info))
	#print(len(lab_results))
	#print("general")
	for info in general_info:
		details = info[0].replace("*","").split(":")
		if len(details) == 1: continue;
		#print(details)
		fields["General"][details[0]] = details[1].strip()
		if details[0] == 'Lokalizacja':
			fields["General"][details[0]] = fields["General"][details[0]].split("/")[0]
		
		if details[0] in RequiredGeneralFields:
			fields["LabResults"][details[0]] = fields["General"][details[0]]
	#print("results")
	
	for res_i in UnitlessRowsRange:
		res = lab_results[res_i]
		#print(res[0],"\t",res[1])
		fields["LabResults"][res[0]] = res[1].strip()
		
	for res in lab_results[UnitlessRowCount+1:]:
		#print(res[0],"\t",res[2])
		fields["LabResults"][res[0]] = res[2].strip()
	'''
	for field in fields:
		print(field)
		for f in fields[field]:
			print("\t",f,"\t",fields[field][f])
	'''
	return fields

def bulk_read(directory_path, laboratory,save_transformer_details):
	ReportFilenames = os.listdir(directory_path)
	BulkData = dict()
	BulkData["lab"] = dict()
	BulkData["transformers"] = dict()
	for report_index, report in enumerate(ReportFilenames):
		filename = directory_path+"/"+report
		Report_data, Transformer_details = extract_data(laboratory,filename,save_transformer_details)
		BulkData["lab"][report]=Report_data
		if save_transformer_details:
			BulkData["transformers"][report]=Transformer_details
		#if report_index == 0:
		#	laborder = list(Report_data.keys())
		#	print(laborder)
		#	trdorder = list(Transformer_details.keys())
		#	print(trdorder)
			
	#print(BulkData)
	return BulkData

def bulk_save(Output, Mode, BulkData, Header=DefaultColumnsLAB):
	newfile = open(Output,Mode)
	if Mode == "w":
		HeaderLine = "zrodlo;" + ";".join(Header) + "\n"
		newfile.write(HeaderLine)
	
	for report in BulkData:
		print(report)
		OrderedData = [str(BulkData[report].get(d,"")) for d in Header]
		#print(OrderedData)
		#for i in range(len(OrderedData)):
		#	print(i, OrderedData[i]);
		#print(";".join(OrderedData))
		ReportLine = report + ";" + ";".join(OrderedData) + "\n"
		#print(ReportLine)
		newfile.write(ReportLine)
	newfile.close()
	

#bd = bulk_read("tests", "ecol",True)
#bulk_save("test.csv","w",bd["lab"],DefaultColumnsLAB)
#extract_data_ecol("tests/joz.pdf")
#extract_data_ecol("tests/krw1.pdf")
#extract_data_ecol("tests/krw2.pdf")
