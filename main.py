# main.py

import sys
import traceback
from app.cli.menus import AnimeInterface

def main():
    try:
        # Instancia a nossa interface de usuário
        app = AnimeInterface()

        # Inicia o loop principal dos menus
        app.iniciar()

    except KeyboardInterrupt:
        # Captura o famoso Ctrl+C caso o usuário queira fechar o terminal à força
        print("\n\n[INFO] Programa encerrado pelo usuário. Até logo!")
        sys.exit(0)
    except Exception as e:
        # Proteção global para o programa não fechar "com tela preta de erro" se algo grave falhar
        print(f"\n[ERRO CRÍTICO] Ocorreu um erro inesperado no sistema: {e}")
        if "--debug" in sys.argv:
            traceback.print_exc()
        else:
            print("(execute com --debug para ver o traceback completo)")
        input("\nPressione Enter para fechar...")
        sys.exit(1)

if __name__ == "__main__":
    main()
