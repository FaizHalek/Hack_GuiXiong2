1. PDF extraction (pypdf)
User can uplaod the pdf into a pdf bank
the extraction algorithm must index and cite the pdf. don't rely on the page numbering from the pdf, index each page extraction manually so reference is more reliable. 
- chunk document per page
- use RAG to search for the document
  - filter different database (manageable via label)

2. on app pdf viewer
- manual verfication

3. Multi Agent 
- Query Agent take user input and genearate a query for 
- Evaluator Agent conduct sanity check on the RAG response

4. PDF Grouping by label
- pdfs can be managed and labeled. admin can adjust the label for each document. this label can be used to filter the RAG document search.
- Add admin panel with relevant features and reposibility

5. Techstack
- frontend (react)
- backend (fastapi)
- deployment (vercel)
- database (supabase)