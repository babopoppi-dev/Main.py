#!/usr/bin/env python3
"""Physical-authorized migration of only the central rented-Mac agent."""
import base64
import contextlib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
import zlib

BASE=Path('/Library/MCPAndreaMacNoleggioV09')
AREA=Path('/Users/Shared/MCPAndreaMacNoleggio')
OLD=Path('/Users/vagrant/.mac-control-gateway/central-adapter')
OLDWORK=Path('/Users/vagrant/MCPAndreaWorkspace')
OLDLABEL='it.andreababini.central-mcp-mac-noleggio-test'
OLDPLIST=Path('/Users/vagrant/Library/LaunchAgents')/(OLDLABEL+'.plist')
OLDHASH='9ecb17283993ddb25736909d66288b4af05d761a701ebd848f4e3bc8e9bd6c0f'
LABEL='it.andreababini.mcp-mac-noleggio-v09'
PLIST=Path('/Library/LaunchDaemons')/(LABEL+'.plist')
STAGING=Path('/Users/vagrant/MCPAndreaMacAgentSetupV09_20261002')
WHEEL='websockets-13.1-py3-none-any.whl'
WHEELHASH='a9a396a6ad26130cdae92ae10c36af09d9bfe6cafe69670fd3b6da9b07b4044f'
PREFLIGHT=Path('/Library/MCPAndreaShellPreflightR2_20261002')
PREFLIGHT_HASH='506636dda780016d3f5c3e81084062a12ebdb1e802aee339c82d8fef395a4b8e'
USER_UUID='51157D7E-6C57-4928-8CA7-DA0A4F9A9086'
GROUP_UUID='64F2EE1E-8D97-4161-8B66-D045B7287459'
PAYLOAD='eJztfYl221aW4K8g8XSDdEiKUryFKua0LCspdWTJI8mVqqY1OBAJSohJgAWAklUu/fvc5e144GIn3T19hjmxSODt79777v4+fztNZ0lU5fms7C0evh0E336g/17ny2ySTIJ3ZxfHfw2wUECFOsG7h+o2z4Lvez90gsmyiK/hVZHPZtfx+GMnyPKgvE1msyD5lIyXVZpnvQ/Zh+yyWJYVNDfOs2l6A7XwTZCWQblcLGYpvLl+CKrbJIhvkqyCZpK7pKBn0GkQFzfLOTwve8HBbPYBBlaO4WewLJMymKRFMq7y4iHAx0W6gO9lEGeT4Cw6Pfvp7OTk7Nde8L6E9sqH+SzNPsLbAsac/Ab1kgmM7zCezRKoNIdBBvfQXjAu8rLsjmFk0M0sH0Od6rbIlze39CtaFPldOoEmp3kRxMEsvUug+8Usf8Bx4pR5HbN0vsiLCuddJZ+qWXqtHk3S6dT8PR1n1Uz9uo3LW/Ptb2WeqR95qb4WifpaVnGlflTpXL9ZLtMJ7sKHbDyLyzL4CbbzEhb2qCjyonX0aZwscD/agw9ZAJ9JMg2iKM3SKopaZTKbdmD8k6QTzJOyhA3qBE+fTpIqTmelrIIf2MqkaLV7qqoo3jaKQGM9bCsYUpPOG9EovBTfcMhyREVSLmcVjcfstUiqZZEFnz98m+BsPgAIw3dqHL6qDjvBh2/FeOh5VXBLOBez78dH30KVzSsDoJPfJ5OoyPMKsAM3IaEfgB1Jlso3wxZ0ZYHO8DTPko6eiPrM408RYeX1Q5WUw1fB02C3v/dM/OnQ+/HtMvsoCuw9fyHfNbTGS1cOd/v9Pg4rngAaJFGZAFhO4PFzc0HTKSDPQyvLK8DPNIMJZeOkVeDUinYA4I5vcqAWcXXbS8v4umzBc8SDIkgzez3Mdmmz4rRMgr/Es2XCsBdC9Xy2rJCEQHnYzb8vAf8moQs08SyNEduHQQkQnUxao5YcQ5YXc/wCw+iogRVJPBMPmwZ35Vsu6/MxeRjO4vn1JA7SKpkPglmStfDbqH8FfRVIpMpkCMStBuQ8HTXaz8Vo90qPw5zSY4f7SbLGFmFLcNGNhpHqiE2qbQV1MhwG4U7o9LjhniSfgCSP0yrIYnhwH2y6RwT7MOfaHmikcKswikCdarmYJS3P7ukpmOjUDr4LWrrTjtuuTaSHNuY5ZSW+QTEb9TzlCO9EQQMHPSUFzomy4ldt9oyJRPBspNQlPVvo7KAADw0IcCTCyg3q4O3BP8YI2lo+/+IZrP7kAQ7wtKwGQQgrXbRrHSL00YCAGpawqEggJrxZEzVY3rEvGEgOaDCLF3BQi13Xp7wJdTDjefwxgXelCQzBHAj+sJ+/RGpH04jyjzUsrRhSsYpR2ca6soKnEZyewTdU+AYOm3TSIhzjd9hV8K9BP++/fLkWsSSbxKcEL/d1EiyK9A5/I8+S32fMDBEj5EexaDrhsecLoEfmxOHZWXT+5uz05G/BP/nXm+Pzo8PLs3P1QPJEPooFLSPEfi4Gqvliy1Z98PponuPjWV4mtWMca00JcmawXy1rRL07XMOy1UasH1nrcOWsOYyF259OmuYHBZIY+BQ5pn/DttLxPAG2dmIc8wKuEaU6BJUergNfIqlloC3oN46tqMr7FMkXPO8VcHCmixaQYxw//jGXI2IKSbwE90WYQGSOYXZQOwiMc5mrNB/N+JVehR8+9ENcXxozPMCzjAomGTJIrXBZTbuvQljkH4Nn/R9eeKHZ5hzD49O/HJwcv4neHVz+OewE+jSnTnwHBcwg7PXUQHolHDUVrc2X9LcARh4Y9KqI8dyMZyhRSL7e7JX3KahxDLQ6utiT4DDO8iwdw9H8jyTIsxng4WQO/B4scAzUpxsv8BCRZEoyJa2kd9MLdqr5AhbWbG7nLi6gGTgCxmcX7X0h1sBhkM9AYFhmlRCLWKCZxDAXKaP0bNygrpBBwEnaDET9NLAIswQqKOujxGJpqOHv6NcIIUOUv6pXuIaiH2vsoqfLDY8D70YfHB4eXVxEb45Oj4/e0E4XeUXbSkM095boDe7GmiPSM0IXq+UnA6ZHHw7MzE9zQku5PcOf4lmZtD3rmWZZIujzVB8ukvqM8MuVpx6MENi5ezxTJskdCtL0Pc3yNh4+LW5XvdY/sYRnDo1Le352dhkd/vng9GdeWevgHd/G2U0y2UcYRTIWxNOKIPYuTe5D/7AtIohnWEaoIYnYNmOrbfs4zjJiTCo+IANztL7xLJD2wuorQOY9vuppImzQHDX8b8TwE9jUYOSBeijIBLNA5vPH4MWzbeZ1cvz2+JIJFnSWwdqm2Q2wJuMkgQP3xTMQhkFSz1DF4ZuUcdow0HZ4nsZ5tBkSEelfVogC1kqW+kz6N62q6Imv8zgDbqSwziyku8apZUJgbZgoBhHyKZprHXIuJknuZrJcrMGdqnhwdmFKh3BR8fkCfY8G3V2XScBPltwbPBQW3Y7P6SBHCoMaWoyG/PjZEGuCMAD7zUOazCbwTizaCMatCySkownOLmhrg7jEJ3UaBw97SVFkOc6/tQfs77N+M/vtgMvF396eHJ/+Ep2dwywv9dQRcgTZYx4j62qdmzjHAZWmRT4PUKfhIe/G5qYZbL27bfZ6bQGIaiBfDot/FOT9PwV0f9gGoeCdTIzdQR1ZUpZpnkXpZDVvq8vZHG6R9KbL2WweV2NgscPRQfc/4u4/+t0frvTXXjToXn1+3vnh+WPY1CN+VrKZF0A+j89OEQEkpyZaCoCCZlVaPXiZ3KkQBSR2uLCwDTV8ElwkRUoMaan07b/lcB4Aw8bHNYjJpK9mmRHEyXwMo0zKXnB5C1ws6Xbjmdmk0ozEk0nKr4HVRYBMxykMCZqEoaM+nsRnPKyAhY1wl0GGJW0KoECS9Oq4Q6Ad3izjYhIq6P71XILy4fnRwWUdrvv5C1JNMnhbIt5KrAOmGZVH6TzpzXOADWTeWyhmfW+Xu79FBQ+KUx60rDerJoU6+d4U59tCysy/T84Of4mO/gqzMH6fvvYgHX4cflmNnCn6a2wb1vf4jGCvYRyAG7U5/jjE2TdUwI+fE8Gxvn5/QVSdtF6wYcIcIzU/CLVFfgMsoJcboSXD0ZSzJFm0+r3+nlMKZV/D5NE7+pRWF1UMi9jGo6vEr56BM1qMb5Pxx0hAeMvPctZ1fE0biJhIkgHrYcukIpQr2008Mw0EBwhyMbC+kZhGq96lRZ8Wbc9Iibp+CWkl0mkvhKswGedLNJRVeQV0YBgA8vT1S9oAlF+Af0ZloI1QuAdplZBE6znFUMGNS9ZQRHUefDcMdr3bw69/DPb6z15twyb/+9n789ODk0ixy4bCLC+AuklqWwqJBAhyXIxv07t45oNU0vHhdFiQ21SEk+p2qNO7iI4vzo9+bmlt31bClpzR4dn5+ft3NKdllnxasCjr6AMB4Gz9pvzwJsNy8yhKOAu8o+ZyPwa7e47R6PfdBCm3YDdv09cNYqF7SsfdKR7Rn7/fe/zwoYf2TGicNieL542rah0rqrSXbapxSU3HiPmRmDKdUA9I5MMiJBSBs3Uy850XavmScV7g+HAyQBviSdniSmjAmLSMDfBRB7VO2AqqllshDnYJRJc5IWDhQxAM52mF6iyxE8kkws2o6cvW7ivwlGd/OTr/W3R+9L/fA4dJEmGKNK5YLhAa9UFQxzIc5F0C0LnWZmZ/VJtAJIfmTM0Xobk6QtY1yds6TS08iCdxFQOS+izDIWJtOFD4/PbszZGJz4iTMIiB1vbDkxvjCXz3TDuM8RCMslKVkw+g+tx9Jx9YqvCIwMQvuRBgSkaRpG1W5QJgtvhBJ/Ahjp+ZsdBoLQbp36evkWFQGMUdO7C8iWyKH0s+HQ5BNN2GLAnp1BBGbTeOZglUNbnJQkmzEKvuvGTjdzweUM6G6u9PDs6jn45PjgjJk5vlLC7Y58YnXRjj0OcBUH3LmPlF2inqUlL3a+EBhK2H7HXA/gZWP55xkV207AguYBiMrizeRH5WsuSqHd4NwhOkzfM0a714/vz7Fx3HdvtdsBt0ucsVtDYjFSc0u4J4NvDrema9eAFYNGnRr4a+FIOESsNVBQ1uaZP9w88Gewi8+31wnTzkGe9fMEvhFFmhWrwOw95veSrGWrbF8lqk1eEUvcwsfry6ggbSTaw1duBoAq6VuQpfbiKzvz4+PYDDTWLRNQyveCAkGgTYC3uSCX3yJCEnJHtJ6gRBLA4OocdVlJWsppp7D1IZFHhDxXyy3Cajps1LS4LT95c/dV/R0G3SplcPsYKAxTIf5tMpSDlDEAgA9m6qW/L6cZa3elgkLS7Ylv0BK4AKFnrFNd1X+LUf/GkoGsZv2LZLxleqVA7Of37/9uiUQJUHsCNak9ZwZElukqLcl930ez3qxlx03JJOECltHhEIR5uH7hRa36chjfX/9Lb1ESTYBH2gat4BqMoj340Wr2SLKqBqQa3bVHwN/gTLQpYDJE/8zKxT426SSSN1RAGMXELIEg61RzSUAQ/oO7EmrkabcHyouqyZdGuKYkGfAvfoaCKOgnbK4X/R6VKm2c0s4dnJQwaYzEWelSsIlIccy1FIQowtOjUV/bVlJcUSks56IDAmJBk/q+CBJIOyi7YCU2Ygi8rHCdJGRbJOyH5iZhPExkZUTLxlyPA1BuJhFdl98r7bLRbLbBxXyaSpDACl7uexRjbmy1mVLmYJ0Y/S1M+u9zeAsx2dNJQ+dlfQBKFZwV97X0wUqA0tgez2ent9IuOWLkr4U6FBfB6nGSooGZVsSN5cJevnBsnxRJIQTW4dQiM/BhZSxZECrKs1GCnWWmCjmtMXodk1Ctwasa6XExC4AOFuY9Jg+5kAuYhdF2OcBZco52JQuRyjzhkeICFFp1pagUe/qNCyxt6RokO7WXYg315YWxQghCNwexTS0/AKl84AUSjTsVenzdT5czhmSTA8PouOzs/PznG9hFcwPKajD2qjCzPKSFH0+BULQdoleMKDHPAUHuuS7ueQoXsgm7ZFxDKLF+Vt3mRsrcPtKsERWegmbYvlEMciorI2be7+QEKJEIxOTn/5UsFovbS3uus3x+ebdC134GOaISENtZchAQbzvuHAwww7kMH8CBZYyZJ4O8Xtx/5EX9yU2Tt+NfoTSIQrdppXP6GY5uU33X7maYlHcOjAV3qTxVAyaQAwzUEpSHQmhes+4l6uyO+YJrRuNHLW5W289/wFPBERDz1+0IImafpX7d5t8mmS3iQl4HyD+kmpeEZ63a5G/PRK63fst/jwSqt67Jf48OpxxSQ1qDTjn7ZOKxSc+ninDZQOq0E1zaSKS3gEITgld+lYP0SvoWaZcp2O7NFDttbAFeld74u0kpAlaIoj7FXJfAGzxxCVHv7zrEUbjp6SvWq+CI0j3NRhYTWhw/r13NRhWQbGo78envx+xkafrvj+mpXFU5/SrcfTpyn7Xk9ny/LWZ+IiWHjIxi0oA3iS5S2XYyClyGIWw3nHS8GrWxbjyDcvmC3CwHq9uOq5qZBf7vezT9DYMkPiLca4Qf8bEjf8LOKydLSpqF8W0MY/TEjDbZDK+slyvihbXKZDxsHoY/IgxEDJrNk0Dtk62kk0sDSaVjYzqZiqdrIhSHmoJgYJ0msgE9cY2Rr0K8IXYVQR8GaszHVyk2YyYGmMldY4YxTpxIOUxhmUVUVK0rXpLCdPCHouXZM9Z0e7zo4brTiWzTVWYWCakuKOmPTlHBUXLeyLjQxEzDuo3BJdRh0aIxmE5VhRpDf209aTsOFNdeIxraEQJKVpQwb6LtjzG0A3AxAUqwDtMd5Qmd+Yk9+vmz4bfVDSTiB3AWbbxmkn2XKOcJO09ALU/ch45eQyeXAPB7REuo2AgqCHYSIYVJeSj3vvOs3Ceq06MHM7PL7eIl+IPfPJR1hkFHIFPIPFGBzywXDZwJ0/fYqNWDw4RjvYqDTAOaFfLOEJ/JQIE2pUIZZQGf+dsYZjYP2AR41iFODJUwL/wQBAaeAboENzguw52fWuE9gtPH7F8B9d/BeUrahLD4WF51N0VZfRBFYEUDEKyZWXVu4ziKa0MFeStdVcoHrFGEOKKKgshmiyRPBUTAfbNCyVm4++vvQuXTPszxG8KNNSaGqQUtscR1zl83RcV4hq3hy/Udjlpoa2JnlJMC1hbz5edAmSu4gAzfQSP/myWiyrP4SHqR2j/vPYYWB4QGuYGPysYWS4SCMzgx+gKXIDVvrdWHxwE+/jNNwy7LbKYMtO87JPxezrB8TgrzKi4wfHMr7N7zNjMGYjDa02N8oNAkvd0CBLLKsbWBI1Metn5dCYqrJLWyNTFumrpuVcz3SKUmsYT4fbbPJVFX25b5vtSs1ueg18prfnLRhM/LhMJiFCncYIRZ8IPQyLhMpZnqc1woM4gVYo5euha4V8foVKxWqot1RX6BL7pVpW6lj090/ujEI3MEoiu5HT8TIWgo0WRVzFZiPLvNLEsFqjyYbgKs+DWVzcJPuBGHA5p7wNwixr9m3QdOGAPMJ9ulrlCcwn3Fpth5gal95MI9A4Q5/5X1goaWcw/NUX92pCD/YsoIV20DMwnz4GP4ZhTNYSKpd6WbHrdjk48vBLbWDefW+waq/eelaJKvGI7KPNBu1C7R4LPKHGVmjMAwJ2daG+4zmyBKFUQp7VT7xnmWhkko4roslAEgTlHSpWEH7UaCuP2+RhXO6lSY9oK6DJR4O4a0BPYWyivVCZLiSXWNhmoWSSVtE1uTozZaNAeGFTnk0iJg2YmuVefZeejJE4EihJy3B3HdlzKJrZuhXJqp57yKA5jK+hhBjOAodG9WB2Z5BC3U9TPKswG3hWwmdAJ2OZt7S0p3/pTPyNSrP6LlvRPRTaWH9AaD1frQf5SvqNkMU+GNrs+/dlAuOqYbGHcCswXEm9mxTwqrbLIONw6r4BDi+C3AHGF8D7Hgn5xlrVKQIX/6Zhez20Que7AUFoPF4WIH6MAXupIcBd+tu0sygu+p57bFZqbHAaNDndPQlkyic0GXdnyV0yC24BcGXUchz8fRlPUDQbB+jY2yVijFmMev4Wpf8FrZ7hc9EeDRASPUGW+MEuiX5SdiSkwhF5E0XkSAzV9Q6MBs939wAqRiV/I4G1VJ4T8CZDWjReVvl0Ouz3dhsYX7ENo5A6As6VnG5QqMXBjPpkYKRxkRkx9Gg2Gjxu350cHB4hfkaHZ++F04vaZ6E2wpmSuwut5zITIbihmWWpJkjKZZWsuJ9At5u5MwEWMxYDv/6gRhwH2LE8CLc4qPXhgwd1A8qvOzDNAwvl2g3O4DVnqtFi6OCewM3VZyprgrxRiivPyC/hX7827BY/mwdA4kcYfhDDCsrDwC4YWHQTbYTQUMqgSa2Z5CDrJq9Q0dd3nODoO6rvL9osMOLnjw3GxM+WoqaxpLiSFI/+nZgk/MuOSSKo+TdUWgsV3W+kokOi0Uo7RpR6u4HC4meFk+vqMFL8+ENJN3UINd88CQ5m9/FDKQMS4ZDRSj4dPNCBGY5nywmzZhh7OV/kVGQMXfbW0BYXCdGZWUJuI3VRgWOiaJM2zVYcrveyEOsx/4hhWaw66ecvn69Q5Rm1GlQmTV5trIaGB9dAsFtiImvlgHl+Zyk4ynxZjNFwS1kLxH6s5u9reVa4jTbyH7V3RrtfzMRz+8S2G80x78vn6xom0zPJlcS2LMZ1TYGYZe2QhcJKHv9mhTy+sY5gcRtDwV3aKsqgmReUl00HDpSUvMZz4DtDNhffGqM06m86zDdHF5fHpweXx2en0dFfjy8uL8ilxdgMiiQGNifLKb0Xq7p8gaMWSknIQbwqEbHKTDmniyLmHKjchDSQNWjSwCnysgAiCc8Ikd6Ln0/0821clg7PzyjZxl+OD1mRQylE2QuDd0oIg2LDGlzxXOql0BEZo7VgWm/wSXD0CWhniRlKb+Ni0qU8Dovl9Swd88YsMOsgiopyW4jMmn34WhXUhVKVoTJQnsvAlSYUmy7C0IMWPAY6F9zny9lEb33bIzXAFpAWt8xw/2xvBkerPNnSKa0WsSM93bCf9W2u8yTTGmi7vQZavtbnjemZEAUw7J9C8GHxfDCjTgZ/h3pspR5buVotX3+tDhkeG1pABTCaWI7+a+Y5sfqoUZY947gxzX/b6pHsqisyRhixqKHd5RcfQWl2F8/SSWAHNurGLO8ls5DpufE1Ua0rIlldu15hxqy2pkYj7H0N3KcyA3utwFerDtOVjiVi50zb8TeW8XjTA+ccVuX1weEv0cXlweWR7VQjCK1qFMHgHtZBJjjgONqA42g9fB8MXtrDxcSF7byHEcggN/pPFteUviAjpPq9zWGiZnd4dvrTyfGhDu2SNAHAfmwkb9jXfiJFMl2WpEDAnRguajz3IfrSBKjUeVBkXGf0EXaQIgFywwz3Qy94oxLUlbKK2yol8IaVN/JJFIlSUe1jO/Ae016hEuVaJtWGg+E2N1KIO8eCHJ/ptOAFSQovtcwekoUhtlDvoQbtqwbzzaMHJLA3MZbVooDh89ns8CkABhPnLZSMR6ekMAbKaWPf9Bye0elYVig4AOJvH//tA6n69hPuBLMcgAwWGRXjTYDk+H9oNw3p2eLT13h8QeQa845yBmQoobfWm7YQgwHkRnqx0Q8MDav2xbIcflbrGWjuv4tvvTPBLZ3dzQ8a8edaAl0nesoPYu5mrQuGY7vmmyVcaxDba1Xww4b8+oxqkNIkneHHOsQT7Y32B+ejWOOegx9hn+UopVYtNrqhN4/RUVocE9Mffj3my7QUtYLGS3SIu5LpmtglbgsS0eQyZnN91mBkNFK42nMMqWqDjnYCoHY73POFz9KrxhBZeotfNvL/9DGU3II03/V7PTvqmD0FO4EKBBTaVyIeZrmGBFlWAvIPhoiHK3IHXHWFsEBmoA6KiNP00zCsZR3J8gwOcpD21DA8Jga0JP0olsTH3tHGNioCNjpQnwRvcpV3dCxyhS6za2XSglXEM4Z4HvIiUUceuos2nOhGBqXVaZPkZ8P0SdbqACHhvaSUXrX88RiSXUv9tSbzF35MuECIX13atwfmh3iQoYADgB6ViWfl5KhUWsqTzcs3mx/HezccCZE4oCwkR2+uAsknrTlJ0DkpzVZNenybznBpFvX03BtPr5b3mBrdKg/+doPWXNpQrS0B55YMhLPOsNDAQuDiwqR0H2zsHKHSEd6116+8WXvNXJnAiPViCgGnFLNaKkn6qgaQCksI34AlceG7OQeoIH1E/fs+j2VbyS6WUvtuO7HZ6rt14qBVm2yLaTbNGwLvUEFOaR8nmycwFToRX/5R27d2tXHPw+f910SVbh5N+tVRpDLUuxbQi+lvBkamHWYnSJ7IKcFTPq5aTXFz3oDFDdJNkYdmOk0T/ZhM2N7mJJ8WSdcBWWVMVUxLEABeXOHdRxUFI0TXaVHdYilYI1KweTug+shhkeE8vovTGaYh5aDNhvb8LTHBkm6SjSJMh3MqROQhAeVwaI9+sHCyLwnXLZUW6U/GkepxbNgkjwh+VqQHGJlDvRLx/6tyjvi8qkVLsDzK96R+aBuSjwLy5lGZbTlMoaBlVNAkS5O0XJCK1AzYVJevNan0lLujKmljcDiPgdBnCcUTxXQXhRFJQw+/lEcu8mUl/fVURl7EcPNauRuA/fvYMoZxHiJ2vFJpHdjftJYbAx9bfqSWs4r36AltiUIrWuxnpmkntI4EM+0il7Ch31QViblssoTvT385Pfv1NLo8OzvhVJQfs/w+09f7Od6BUvP0ecUCbDA1ZybOSOORCQ5XhIrypy7ZmJxJUTQFsu3W06emJ59Am0sQ2jbOy+T1mRe+GQDARg5POA2hT+D1SztN07edgO9WLMe3yTy2Lld8e/iO15zSL07jcdILzgUoC2RBuTJm3wjpdrqvQTwtuWoWz3rypkFEYNxDecqKyxDJDDPFRLSULYWbkuirmBqsA3SWq4ZGXTbo6JbCNFssqwuaU4hX7am1DFEqxsi2/BpPV4piUNml3xUoplfMKXFmDKOmcqwdBCNFLa4o7pJfmIUXZlOfVXH8LkfA3m8EqdlyTq3eLQiRMYt1ls+Sm5s0l7/n8PXqEW1VvEyP8g5AvGWGSES9XXuFwgPr3hvklUT6bHnJAgwaF4UvW+ghNiNbTYh4gYI7z4+2zyZI5/DDSAVmXGLHbe0HdhYtQAPsh04aI2mfeF4G9KsnpeVxPr9GYMOhVvc5RRTA29MEaCYajEV+KxxRycBNOcGzSc+ifIpnwhUzMybppRNZvXjtpjFQWHjaf7ToZ8hzaKqH9/DMaTv7tHOfxC9KDma1i0+cptVKrG9912r9+d6zvVevHgE+VGBkp7Zb9ROD9m25gELBXp+3jt7tB0nM6XkwruGWVAol3voViMwxSF4oVYxvie3Rx0URc/oHtErp5YepHIsnYi7y515fT6R0Z2LT+F8pAIUGTry/e9VrLzjgKBypY+EoHJzw9RJl65j1LOyPshpedP6tGq6528hpKlaiej2M6sqCDlXA2FRjEM6q2GfdOTuBwpkSj4VPO90SdX+bZEHNtVe4LAOOAtoU93jOzJIY8Mp29XUXR3mdGhil/HsbZg97fiKxZ9dZNO0QvMEKN/mab4U0uzWMfLS6GRlztGfXsYbr7EWdrZI+6/BoWZCPy0zcV0BAK5QXyB6yioMVWLglWhpEQsiCaH0r7F0gDea25OmVtRB7zZTEx0cd0jM+7OcAivjDUFzyLA2XSYWdUNkafWOvFqf2Ft2U8D4tdtmJLZ8y6gx9zxkyhDOmuiDC8PvYbxiStbTKj0QtrulFosYsijkFnEnUmOef4dRiYd2Q1TukSQXJcb7gC6IJfykfIeHrPqCkEm4DEmWpBun4l7PZCuBoPh4s3hdG9j6b5OQxpXwTtNvClA4DPhtwSdmT7xYpRmZezmWsrrj5Q1zXVbpDdGwlPsoBo0ZOEh/+H9Mx5n8J+mjH4wNffSWYl9ODt0fIvHyuRsw/smGeeBTN3QheCrlTctSZzQRH3JKQ4zCjo0o3o4AL1X2qFyH46EEgq6h7ZN6bbiGPcJnzzHezOSVKpb0/SbPlp+A+Lz6C9Au0m2qSn6KQHIF5AtyEnaEbIYgFIs1lz7nkO0bjZZqr35TpuuF+b+s+bzgnbn2Xey+qB+9F3+hRMvPf+10ur4Xj3WZXgR8D44q6oQuctNiItwd/jc7eX757fwm7u/dib/eZyIry+tfzg3do8dvJF9UOXsFexLMu5kAQK7UD3OTO9X0RL/BpaKVnsK/NJtDu6FXvBON4gXgndIBmBjLUpTAqDLme885oROk1tbaUagh1qSppy7lcFIOHZHVy3LHa9kqN5uWufO29BiNpuYvVpfeea+uoDzFzDKrmb857vBMWXbbs1Ob0CqhWStd/9PrOm9/ya9JvuLlEgAEpk6iKy4+qRS7RkKJZypytMQVbr/bA4zJfe1tTvSe94u8UOZf3Bi8BH2GEbOuSGLvyeiZ5xQB1Y8KokKzknfe1YdACugtSWw9rTyVQ8R5+MxSt+s16Q2NTN5s9nNPYC5KkVGAy0y+moeiPNZ6leFBM06Ks9DV/RKs47peasOZMedZBnC2/bvKbTcEZN4pE2NB1Ahy1ODESTk5wlxSsEvfE38oBN0XciveUm7Z28UAdmWVxhcSZzEvNYvAuCXbP3HBaY6vFOBDDmNdwd/tPJgaT1toDJxviQEYChtzqW+CnhWudfagFhPxfMeZVEBrfx6nY/wnePTyz3Dt0Lx2bckmI87goyE14Grzo14dsEDIYN41ZIpt+1ZvA85rduU4IxdHdEzw4PhU6/HukWxEVbnnuKfksUHCinU3EsDFxJ3/jCF5MZxzFVZQs8vGtnRjKmasvK3Q5zolxcw88kJYq/MkpIUseipY/IkxedYe3yitz1a6veYnXkewnPDsAwhogdQVJ4x/CnZs8LBAVJuldOlnyDXSVzvyoqYq1bjjoNUlr6TIIPyj6nW23gs3NYNT8NDlEcAsSXPgGNMz63tsjbVur19+1ALxbG6gVdCp007K9QzxFkd75FNVmKhq90HIe7hqvYQ/8PAXCfceDHs6TjlMNt0PgoU0/jIcKwzhOhFGsllcLUXZMi2BuDEU55tf27fDI4Oib4ZuJUYSiM8qNSQuqrMZgmbO5WGaYDttEm74d2Huv8kzG91aetfg+cFlHcniH55JMkWMFPNC1xvLaca+p3+RgsTtr4bfgVmvnBh8KMBfj8gW6GxjFUNWWP3RODEp7Z6k51AOTTc9Lserhjm4fyF/LF+ba1ry5CLy3slrGxc2dZFtAzIsxHBvmwkuI3gWoDJjaaS2FiBnuLMuChJVFwQHqsOndboai0/DFM/ErxzkOd/de8e+4HO72X37/8tnuq71nPssflJmi0mG4++Lly5d7uy+43jgvkmFffF8socF+KJCMBCp/S8usvI2LpAvHI1eVD5Yl65u6XYH69CQr5bOki5vUZS8NMZPkvitAuWHcwLF1J0W+wPIHJydcrci71+gXCz9wvfRfbxPCw4Lsiry4VEH8rb2fpdf0nv5u0iAU5J3R37pd3DB6Jr90MeKOntBff8N8o1H44uVu/9Ur2VQ1X0xpEXcw7bBYTJ40kIOGpnB9ulNcIkx+yYCH3gsGdPO+33JbCJ/+DQDqCht2J9YqqcR3VC7Jhce1HPCC+uelav357C2FxLjD0CVODk5/JgVjj4xLa1u8PDp/i38xum/OjSF66bkLZPO3IyFh5zoubyV2wZZJpRj+LHj/8F+BzleW/mACREzmsEVCPrDPh0hHwe++2OxSNPeCKWh1FE7JXPBq9wf3UtONL2z1sQ5fdEeaTAxHv3pHx2edQHx9ffDmp5X59Dcb1ZobsXxVaI04cSTeagHg0HATFs64LIU7jFWrDUwRUT+tZ6oNS9T+0ZuuZpLM7HGMBlzeEwhC5a5R6rnClBFcrs5FkfbUkYHNQ6UWfUgTkPqCJmHYytonGjNVI+Jhjz1Q6bG690q8w2d0h5goaqZk+n7v5Qu/e7kpysqGtBuBkA24PluEHZkQPVt/G4VEVK96i3wG7JhiX1TOifVsWAPfoTkjGZGHUn8cCLZLamDLKl+wNQJOOOeyrifBGziucJUWs8S4mJvS/0iTZF5MkmI/YBlIlyCjD+U0wuBsqGz4f7Mgoly4cHYkWuy+8MmQNHlMW4yX9uD1pIVRzeTzS9iB6/xThLyW4NWQhYT/jUJ0afbvfIs2s2meoJN5XFYkAZSzmNJnIwEn/zf5nVMQDoOucckvQkRdaqhRV/PebJrEdldnmwzmyuugn9AN52yMNULY8DaEjoItaoFdwXDN4XgGSJ6jwcfaeYJXOsBtvlt5ydoctkNrLD9Xg7fbKLhrzY2SpNeQzqLI6/f1E8oB+a+083t7jbGzNQwEZjKeJhIsYQWT8bIin043xw+BSUdByaJ6IOCEv+5mKADq2PCDGT/SRU3SxsVKhGkdkL4le/ItkFvW6MpXXECptoX03hFCMdFGsUGTY42YtuDAw2+6cMT9YFhmNqRFQhI/gZPJ+AWntvzFucym4sa5DVtHCYrqtHwj5MMrIrM5k7ht2sbDDcQuYC2yu+Fn5jcHNX5TMIwDzTC6VzupJD800fa+gpjubkNBYw77zRQHP/gSE3PCSUU+Ly4okQjnD3P63qdn8uhiqYmtkg673KMBk8/6P7xoSoQNpVaxTaochwZhcTzqscW1Ab/nqO6ZK3uUwG2O1BNJ2SgWquGmPdGt4giRyNBwRYQMZpOblChctq7Dx5UXUDekl9qYhcaPP2DTp3/r9d34Rsl/wei32tNJGt9keYkpDvXGSsKElzm0nXtAO+yrVQ5leriwLbm5xum3nPnr+882GVUIgoHxQLDATYTfDxJoiU0xtoT9DqYxIMVkQMFVumlnAjI+wrjrnICztvBkjqHSnEKXTOXdBV3z7Vhn5C15qsQV5UBtPMb8s+Hho0FGzat2jJVr7jPBD2oY0duTQzEoCIO0pPBLigTMEQ/ogIFfUywpwUNwawNm4xocw8V2DUxa1glYQGHHIfRjovvifGYAbAItGngrhUCBI8zdQ40QVVVaTCeJgWJLRzAzdLKG747KVDSIvjRS/znLc8T7eDIhygbsreIHODYTZXIWxz1iIpkAxJUT6wwsUIHUs172A+pL3tg9GnRaGutyDtq9BX3HvQIGZKLVuuqhJdc0XS22leWlfk3ba9jaI/oKo6snQiFWZa2xwzPcJqqJJT+msxqrrF4iAW0hGiGP8r0bZG0rD/w5/VAAnFJ0Y8tiDzt+FrDDm9eQNAUa+rE5K63vLumakQlhx6sXarIzEXR6hVvPMPwnznNv6DrrqGx08K+hOKFoJAJx3Ut98WO9b4zkXYG6lMYlkdirNFz+3E+81JsXYornlqNXRKWukGtv+TZO22S8G/ck+AVAOLheXgNWoTtRiBIbUHfgFoKakjtAeC8peIG1Cu+O35hWzie47ePbACluGUzQ2ZqT30xUVhszw6SQGZIyWFK8B8wB6EnLTFgGu7cxDJkFXcS0YQt/RIBcLXMFCV2BvH9v2T5gdz+KHK1aYVXacVmbOWwYOqpyu7RZZVO2LFP7JNNiCfIc2Emx+MjVqhRkGEorjR2vtGnhZ80fHcxX2zpKyFGYfp7ANxh+Mh4/ITop9dKrBBuNC2/MSuyTWdDYIOOScUZ0PvuvOqba0kr6gEfgPBUKVanW9KhYO+pS6BfPn39vCiPyIgfU+tmV+KbxoGt2PsAurSfmeMwcA9YEQKAyqlgrYxQa4oRqy+09yvXJraimwA9ML5D4bwYNk0+AUOLO3zq+dgx2DFdlPWvv68Mb7A1N38ZlNJe3ek3sBfFumceJQiyEA21xcWM5ZvH9ZMhjwQvmucXdZY5SV5Qb0jVkRdVwRathOmetuNmvYOlZewILYj68n1j3tjVjga5j7HS7cbCIcA1jZX9NREjZNq2pcwmTO/d84Ta3ibtAM4iqPjvc+sL0BmqCQW4KXzw2jhRjV3xq50a7A34EgutFbri/xCH+HAktqb+8NcSyN+y++P6Ve98lrYqH6uNNZ9KpgMNkYGrwCERLbqdudxDjslkeSfBrJ+0KhtnjmyvovlQJJ2gecPtuMBJSJA9pA/gSNMNKaK+QXXdjXYfsoL8tqPFNLyUHTlEr5uV8tTWQwb5qLRSNcMkOa4Ndl1CX7AgRwgI18Qxo5+5e38ZAUguI921l2kyR9ZrO8rhSTAc6wwNVx4yhlVFDOMxij3+qywv16S7yMiWzDzekKvscgonO0Sn2BxA/Frq5BzvU2TgY67AHLDBIGuTFKZ2aC2Bv8wyjnPZlgj4UQFXimDIgK5rooucjcRuxmshgiOVCvrPZXe2SCzU7qznAvJpcaxYLZ4VqftenTRjyhsHIRQuFFFJj85viETnE5bYmwXvuSQlW2TaVyFZjPa5qE/0cCr9LynIZDsTIKcowLyY6zAmOB5mc2fXVJZdg9PjhWzW6wgQWNOUdYG+uSDuzfakz8hf7h+5DIxgOX1GWUswUGmc8BXQatYqiogSjdDD+mqRIK0TnJ+DN2VIi7zML0D8mWy72OdwSsQIouHD6h0bOLmCJZdDlg4iQceNzzMia+0ljOE09gqZ8cKNpPmTvj98AID7v94FuYxASqmbn40UEywsQHuqoJ0FwIiWJSYhGR+aHsge8ZQVTnFMe3Elc3KdZiNQuJ9KyRMkTX2F/6mliPh64VL8m9rhLBbVx4IZLAHkRImTQq13Eg+t0AiOWZJITp0PXN/4BuY8/9zvBq/5j8K8oPrdE1SJfLhwvgbUjxvu54gmQpICq1+g3asfuJ9j84h5XBfpv9xb3EQUwwnhwb7bpT0WOyGQ6bb2VANxlEin9gLpAFZPEAZpFpGUEjMMvcpIVBkELX86qpQc9Uxew8oXiz149f/miNlBb4y1TqoNQDYNEU7e6FFEuBxIwimrDhLHUvJV6xnSaomQH6KADr7iQ58ZzLkU7+708ofnZqI8UcJLeYD3n1a7xyntS2/OSSoLa/MxDmhIlLVJ2T6haahBoz9e/dx3GHy3mQ4ZKBG+sD6utvks+xLuDVMqY1d4VMwVsAwv/o2YCE3uN+vLWQon64kwQLzU0iQdqheqEgp+zz61ryx6xQx2ntejGnyjsFWY77CzwH7T6DeHw86tV+SPt1EbTx++OtMXafY58/HrTsmPh3tiuHD5SNjHscqUKVyJdRPkI83EPGbJlRuir9Np7dabFmI7kWygow00fZ2jQ9+sd+PTl67EUXk5w4HaKGANMqR8tEm6AM/Ve2A7mUWA1kS1tGWH6vEAabpA7PhgjhtMWFYRH68BV8vqEQba9DzEODXzyO18HI3teT6WTT0Clxmklsje+A6TWR9h1kceTcVxWKpiqforZ0PQkQOMZCd3UVlqyqxkyHdU9xp+JOHGEhg4xHR+TIktmHFRelaQ4NNvDw4qOUhHlV+ViETXbUuK5VD9uDG4dloTATy04v5LW43e8jyekUxEGZGelzKWUUSNiS6t8EaneI1rHAqjJuk2ViWL9ThYiPLjRuULWNoZ1jTplbE0SwZpimkp41T7miv9UJMk/EsklSt0N3e2EcaFQo4u0HXdiTF3GAniuc1TtLsvKbE00g1srTAtCn4M5cdBhsEhgG0F4pg3q7rYD1NGgIyGz8ZbUNRVQjtIE3ffSoinVgtG8WIbs68XxzxeXZ+/av2+TvxyfnJg6XNwuadXaM3DYOZ00Wtp0SIOytpsUyTzGREWYcF9y7oiCkuMfowxjcfwXD2WVzLv3GHyiYEdDHc6bWFfTTvPuAQSK7PveD+g3SpkdXIbfiquXjLtABJKsoiy/N2Cfz2lcEBphBAtAAXr06JB8Fd+enZ5dnp0eH0bnB78atJKDo+SAWww9EclTun1cFb7dDVX+/V6/E5gFfcFiaj/qqhHVXpudZGXrwN88e9bfre2bzyyja1mhoVJeNxaJsnHJwt8FuxhRJidPbenJk8QsZw2Vkfc1WloxJa4pmUms+ifheALHBv78jua2t3Ju1/EkIMPwJL9RIOTMTKQ+lAC5yOFcebAhMomr62QGoiK9IxAkC5TIGqHEdcoUIUR2zuAEtCa+YeIBiOECpZX5AUVS4ghQRTFLrwPx/J0JuXaChweTnMfTJNLOmxpbuU86FkSGIukFWxKmSfdykQflNhEJwqAAo5XEKTV6bJVyYU/iijIxjK60xGH63mIslwz+kYFAJhHRjUg/uHd0DZxsoo2XrBSY1lhCvxgK9Ekl5Q1yIGbP+Ha5B2xKLoJTK7IHLZ6KsT/BJFazJCzlrKWzPEzqPi4mtJd4GkwxyR8p22JMLDmWV5rJTgXZV8UiKCbHi8NDu0/EyYfawQ7mkeK8NuUOd4ypmHcOOQNVufMWSZ14Eyp0sRrv8XVqNnmuzVhmeLaqivWRaeQswdRMYK6bsdiJ6lZmny5gErM7iyeus+u46rRd5Bm9ieOz7fdcc3vexOvZn0pb9ma1sLvr8zfzN0DHL/MFacaz4p++y50XPHN83Zv5Ju9bAMyDu7BXYFFbgoU9A/8S4KfR+bsqgPGBvdcALEYa1uWmVu2mjZX8pn/1BLCRZIzRYpRity2R8K8o8yBbRYb425zGBkjAeS5lCojrByDbN0UMq9963t9F/TvwGKgaAkygVPs92eAlEbSCrt5TCh1SeaGcDwvOnsZA98pE3pdIiX1StcHTfAaMnbwawMSLOpptjh/qLiG+zxcNwRjQbIJSjZmjLPVeCEINogQOqckAngIXx4cq/e0DBOzDICBtcnmbUlgO5eJrGJEBnH2Wx0Rma3Ocr/o+n7BG1w3azi7uHAGsPTQ3c61LVQwStDqFeK1jmQLNWQqfHWkVlEuWitl2UdLULXI0ZMvwMKyqBwr6toLPtJlA36WqTkI3v5FYCfXY0l/tvIc1LfHag7wwmuUTnN7RGc6lLoiBC+vSgMl5ZTH8vTfa8ihr5aQIKlo4OvnEHtwkuduBNyUPD8PDMaWqKDp6PrhaPRSVnzcWOu93l39TPOCSc0mNwhZeNoUn+W4b59oCUoFeYZSsz3giPD2ftmt2F1EAk9B22cvBqEZPAXwwVVthPEcWIqE7N7soPja2SmYfNJc95coENPppV+Z9N5qml0TcmgdLZTAYyajH4qGvCncqtBgtlgpJu9I2B+W8l3oFKHNlrvl3tOhcRYiLXSCJH62mHspxNaMZ2rXVtSBOA3iIPQ1aqN9DuEIvdnJSnyzni9JACcwvAAMyOB3j+EOJuomZ3nQEM7ryZeaOwGBN60OgIacyJYEZMb9Tyi8sHNPXk/S6iIuHHWZbvSn2VZk3eK0GZu8DxpK42hOQWzDHddlQ8UCztuUOncndvRe9F70+zltE2ad3cODt3MXFzuR6Z/IwmzS05ZREkvkPtJoaKd+u1i2vhv/G3eVLKKxVfRLgsABnk0lJznqGWIaCDunnDIGlIlUhUSLk9EUa2LLd826STC2wgwkh1Q9gSib5XP1cGr/lQiTVeIeuSqLTaqu5N8CVZ+7NTTFN2BpL1jcoB/fhW7UsH77VDRgUf4spe3twhiybdUcs8ot8+JCJXCLUGZXCZ4YWinI4ssz/5BuVESTJ7oIFq5bgbCbp91Kwy4WQ2roccAZy03KhUscif4qojsruXIjUQoUgIlV89ui1wr/s01UAkOmYlCcZHNAV8lPIcpDEGXEy1KitWVDBXSI3Ql0qw3ug+rE1v0Y5oQGRpnNmVDTngkqhtQpkYU7EUWMAJhkUn9dOcKZ0R5/SygwSx6BpKZhXnpx+ZhJJDONUwZ2K1xgGsuPR7uBKjUjyT5wllDiokd3YFQ3Ul1anPmAcZr6sKIFOLXmO3Eb0iOeUMy316Pzk+O3xZXR4dn7UIca439681ukZZj6Fert7r9Dt6tU2dd+dnx1C1RfPOsGLZ1tU/Oni+D+oT5HoBjoW37Zo5PDdexp2n73FpJkD0A+jsLwGwwH9KumbPB4p18nAAALrPAov374DodosQHmGeiLJizQ/Jln0/kLmQhHpTgYy3YlwFcpZzQTopPMHCdQmFiDsmJmFnDdhd1E/Klcw/e0NU6a4TdoZVMj8KqSMFJOwoltEFJF7aRQh5kaRdDFlPNb0UepQtyGRnQAFR5p4MlF+JrKlQXB09tOO0upTzhs2ohkWsffHb76IULICc6XPzh9NMztN9jWjAbIsyAa0WrzjKNG3JK+GfU7lerteTqcUO3cdhqaBDs3yVk4sECKAOe0EkboJCRayx39aoz4A0Uj839uzxWxZ19X/OKHRiOH9vWd+5V9T9plGU+W+NzGNmC1IGNRgrSs8fbjMinjqLfvk9bwmvoLyjlD7nnZxazrGhtAX4XPD1TveO1pXRCrrDXesL+RN28KvvoumhFJPi8oN7W+xEnjtnxyNdloUViO697Nm/d2why+hWmSJsSw5Z4bVhnUBVKbDJi8KHI6zwJvvUhIwtKCsy/ZNgsOnCsjTRgnAN6JpZgLwdWm+6wTPSflNvZlp0WWXVg7wP4zW2RZSMwf523hMXbesgUiSd3L2c0QMQ4BZeIKnRErEn60SjM/ym3JVmvEliMpA9FU7jSnKTc9xyuSDyk5h7Gk+RpxKOBpZCb+7jeKz3vwj2sFQWTns5y8xtw+ZfaL8IzlXuXWU1dPO7L19ruemY4bf0dU1yldeLJto2m3UIhP2IFXOY81orIqjFM7jU+j/VvEm9sBI8uPxbZSsk6945Iyb6g5AM9vmZnk8nTPxKxJyelJxkiBpp5bfMCGne6Eoz9jjlr8gkmNgkjAPUdhSzQkfFSLyYrhWaDpwywu1pGAtfxuMpHykDO6qjnAJqflUIpK0NJrt8BVvjfaQrzMnbpVDCTe6ixYRlbo8meHNHF7TgDb8qLko64968mUmoJoB8Y+bsrAK8UQNk6EBO5yMSOGnNy2xQadqfq32WEa2bR/lnmOSfl6LtJMmZNSAre36v4o0TR6HV8cR9s3RX07fn5z4fGHlK4fldbxeG3IyqXRLdu0NfWRNIfXRJf4+0qj3pfZ25cb0aKFEwBuZshz/Jh0t0laatbYvFM7X7HS2LG/t4UXCSwwBtT60Jk6x+XCpZ1vwDMQD90RONSfXw3tEYd3K1usi/5hk71Jxh2RTqh7fdDlhgi9fhCq4MifHqqP9/2dG/W+TGdV076Mt04yrCKAHlk7cQXhV68103/MlQ5ENYJgeYSUNbTRQ9XzZOtxeUTrG4D5KKErJxzq6Y18Wj/+2iV73mxK7Os3rmUIXaqor1jeSGUV99yZbhYkqAXaUeB0ZRn/xIEUyugKveQQWwKNjoChzk955dk5LwPjrK/LUruLk/wfksF2dwtYfrvmflcDWYtP/mLSyK9PJinQGJi9vvP3aZLN+Eoufr8pCa+b3mhnHnZqUCtV2cPO/LgntJrnlYCrSEKWE/50Ac90g94S/XU+qqbk5xIFxE22xQ7+en52e/M27R0d/PTxpSA7crg2Le5lOqB9MLRreY2J+VlECLA/dOltkhN0mxave2HqOK4ZkR7Jw6jflfK3D6fYyhRJovelg3cRwtg0S1qCqHlBoFZlRfTF5v1/62FVyh//yga+UPcQ+b5b79etSLHpJjpN28T8zxSI8QMQdIBo1tIQchcw+YOGwwZbxoCzeg7PH/I9N4bjvJe34+W+WzpFDavEWcLxRXLe4WW5HQdJ8dqZ1POBX5mH8vRIuOlVnNcEaP/BUy7guw/qfkqJxK9XyisRB+PHz9qplyhwULDPpXzp78LD4+NmIzd8st+ST4GBWivjFpAwmcTLHawyq27iCNa5I0FARkLcULZdgsoRMu83QsHseerJqhP8jc1ruN+Sw3DdFbK/K5nfIa2mukCOV+OSAVZvzxakj1+cvVBYeaduxUvbYOQw3zXXIbfaWCwyYaMljcajEbr47m4x06hgceoTyRrnDQFmsJ/LLGXjsubxRmorQdkwRex7r8TsolBR3ibpqRN0ugkz8vhRJ4e9dmqAbYFwAu3hHId+Yy6fKC2gazZGzWnyqkZDGvN6ZDL3KiMq2BfFOmkpN8+kBjpwNqPK13E2yfpHsgqsoxlLTr8oMZFVexTM7ExnpQ5GNp2AXwRqTuZI0dVmFt9B7jiV8Q8GA/iK0YZT/EYpxWMYm92QYKOSmJu13f4i7U0pN+uEDyVMd0TrZi6S2YkPTkJl7R77KcFz40hcvRkDVZDNRsQjiElY6Rio7u4m9F99BL/tiP+A79Y+3lnmXg6ugMmHvFYUxcTVXCfljsPfcMZ9vNxE9+r8voQup4toXEJ8QQshzCCQQdeGOL8fcl124VIflOlLbZmk7i5vZg+EzQri/kZvbG09eIqrNKZSEOXBM988Iz2+OAtbXzTOJ2d6ZZMX98bAgN3A+CqIhfvVuYaYztEeKUud5RZkRMJ7vz/xuW1fkxpxZIOAnhndKufnt9D4/vcOzN0ebOFQ0+PNhdaT2K16jZA9S3QTEQOXeR/1UGB8hZ48rRQETZokSgHAeqyLHJ0cR5pi6EGWMc0SW0QT6d3Cu+ZC9PrhQq6OjPd4evjug1GNwBpzmswRgIP9L/wfEvYvLg0usQRV3KPsrHKUfsl/Pzn/RDZlxXt7WdiwHhPfnJ8QYl+VgZ2c+XvQ48dl1DJiT9tJqhxZi577cwdlmog3o9S9H5xfHZ6dYud/7oYs7Gc+6u/AGaBWaEQT4AgE+ga8J3sY9XnS5+S401lWNwTDOKQ0bnAZ4PKMrrZOmGoocHpycHJ3XSq27hx5rnr19e3D65oJ0FuV9hNFiIAya7r/iYcfVDIWfkAhcLzHVSFdEmdlVdQFSPskynAdYZIgSutsKbY+KRRSKRLmbMsCEiRgVFSKJHWwqsMYXc+rzO2jwOfgD/A1W+xqMARwRKeBIU64tKoDK1ZGaCtLzN6aCVOpBZciA4GtMvSeQAmRqps4iYCnmUEgbnOWt9or12NTl5IYfsHehu0a7379cz3ZsvGzkMW7G6COIwMREKs695y+dO2saWCyFJRHgyLPvO8BOYBp4am51MKbMNsJZMfTQnJgdasnkbN+kQG5IAWXws46fHxKlIVKyDh+0Q6J2dc8GKNZRiV0r5a+HzwFiOFEDvnANKBwdPtRnQWukdMRU+cpQGnPTgJQYdseBdGHNG4LPhqHJt+uejMbE0OqNUwNd5LYwCa10aPQ5BAonQ9/Yva155wKvuixrY3fz+BOfyKS8HO6+eIqc5FPHv1t4pIwTEixG1k2uVBs5MrGD+YIz6XZUqL7ro2flGCZJ0egKuUHyuRuuWSoDacuIFZCGcZN9AcmySZHJ3O9QNy/iAM0oZfWObq62EuVmN+ycrbcBsEr0S36DesstYiKKkNV0ofwcKAd6JEM/UCVCi4h3rOADpOeRQR03oxSKn+cbMSmkGB2dHUMqDENmYecRqLSIrc8hMLVlQrdMA2W8gY2RGT8pW7Q7ENLTiXdBF85U2kvyAPwklOGPjc5odi5rJVNxhGdxs5zjCeaKVPJmOA0+uqtOsPdib/eZJyyB8tdRVTeDHX7dxWRE3DAms6tl7mwets66BGMuPddUcRL2iCRjBKAeKbn4WNtXz1AyoOzsrtJYKs+FxYFBOhQRreKWg9GAhn71Rbcd4EfkHefOyBgiXUpoSB1eGjRxmFcjqPcgh1IBM1c5j1tMbyKIfstDF+pyJJp1lEdaPUl5DeJk9m5cl3v6I3OWP+L+etJ8SySUzOBaZwW5y3JofuhMp276cIXtZL5wzoEtblrh+/6oSWch5OHTkwm22yM7UbWrrm3iMUpWNMuLdYmQyLzyQgEgXSFinRRajkyurEHk2Xhr6zSFnUnLjBSc33oqN2KE6zdSG3W11tnTdOpEC6vSuzckQPW8v7h8c/b+0vX9vJ8M66f2BndyrjG9ishGt2kd0mi9weOOohq9iBvC5I9Ozt4dnUdcd024v05GpdIIWGbf1XlZG5TT9WyqnWDXtHZsYFdr9NCs58VsD0QqzcVNS5sNGzMh4ocHru9Jw2Ak2xSniKx5sYeTvtW0QvOX0YDu4VFUd+urZex00dSYoF2TKKeO5K1/LoVU9JQp5BzWCPhwj1XCYIZEIXTiGfPdC+KJuOYBzseQIqND1FwkZf0umRVnH1cwvZiEdq4gRxqrJ35FfKf5OHVpm+upJm0QhqMaqwEMkUZ4vMn3RvXCvQjr/PiNKQs1XXxVI5QYToZHF6sMRVJY6cgGqxCk2qfNnJE8+tzlyBe1pcBiqxeDz1DayUF9X9ThpAJP4izIr38D7soa0cdNXK6YXYQzTKvFvN6z0r4keWAWB/SBzysFSNNHdUU4wNQPRepapOF0Vewphx9FuEmsfHMhUgxPcwPfoFJHhCkB27mSyeTWm9lMa1bmHSJ02jqhUXxsyZ5ds6U5KeGHYM5KMd/Yyqq1rY1CNObaEc3+xA0SGLC+bvUsXopZKc1JrV5MkStz1VrazJHixJq5sFXTVywijbxeD8WxwYrdE7fhWPfgrFtDcehvtIziIp5ObT3p4qaO6QqzbmXl1T5fBqfyurENZ3p/m0cgrgpecnPI/Pz0qY8VRQ0cKQwiQ3kyMDUJo+5ef3D16I4Id8+zKsgYULK1QLXnLgcRNeTL9l2LsCzhd3SA4eTkyvSZYB5vfsNUqZQrmNzE+NQynNoEvWd3poId39SoBkTvwxx9j/KPjw0ktWWiZ8cFNNZaOFS/dmERnmnercH5GKy0kJiNJ6MBuVo7gQsnZz/3UAnRMvLycGNofS2XRRLF5ThNWTnlcy/hnZWpgD5/HNyR2vpj546iVqgtTAg7FzfwkCpUDct1RMSAARNgBt3dfv+qzhMJb0X3eqFGkrlvegML55B9I07XcH8SSRtEajY3ufTnELNbokkaQZusZrhJ8iFBj7wQhjzR+D4YfMrZYAeUyUYYC+StHZijwTE/sNuaYcfmOMvblDwbQ8smA6/YaqXtFMJI47aqD6JIqB31RXfafGa0E/Z7L91gNwG51zHMHi+4w4vuOFFS967/gwbtBoc8AffSjQ9EINT+1uwvIq6B9HNIR0aq5FVHaLNQ2RVJHZ5oi21lrpLVaZvmnsLSp+S+KXI6ap4n+CfaiwxsdZC142FXOr7TvuMS2cfaWOTpJrdF5HXWw5InpiCweZYhaweLCsxpDgxtOt4XR3KR3OWYIhpOEBiLLGnYo8QjXFXAr3RRtdQTxnAB7PKu+M/CZ9O45KHjB00vGa2DIymzuEO68058f7QMY2oL1fsekidhFANSsjAKtXSpLnKZCAPmbRjknk9SdYPJCdv7XXzyfSape2mSUvSVU6R3ginQn6mMpNxnIxVQt7qRikL4SMg0h2tmJ8X/zBQBGCtCS4K8wG0SF4CbcdVRgmSizhD1sjfGM0dFRtiCQaPELvUDh1QZ0FtkF1aif3vAJFn1I/agdihjh1xUD7KZ7ZX16+AsnY7sJTGWo74GZNC/T66ZmJc9oKnx+KHHtwkH2p0DW+gEvybXF1TwkN6/K/IqH+czf1OJXAftwpGwlh/dN8rb+KMQxthadprL162GbqzDTk3vVjYmNARPWQZ7+vTjvatOlWvtdbXR7bgtOBwbK3lqcxn4rpcoRCkgTr8x3teu0OGZSCjDdW69Pz/BVBlVEUe3ZLkqh5/DA+sCOiCArwGsQB5HtHcs7Y/N4U1lORvC/1I7KZLFRgK+kW6JNwux6EO9L82tIspHMgB497kM9JBPnuPNV9lNlEInBVCAISZNoyfqwqOGWAb8oMkDrQ3DPW2rY0MeMKXLZPiKHKMIJ1FRSZ5XSHbuyxpzdI8RPcCoGfzeZ1YHDUJEN2AmQuR9woHmgB6tiLUazrV9MInIXvOJ9aavssdnu1Lvup7Uv+NEFE0a+uIiePwr9aU8WWR2KadIZi+3/ICsMKyHSfhbVPtd3gxpXrM8ngBDHt+jGhMaghdaf8bWRq3yK286rO0j86S/T/zUFUwoz6zRltUFtDUaMPNDR96wRt+VYhOG3lATT76HodpYlu5gZ5EDwVGTzEX8q3w3oM48d4MKqqXOpuZI9S9eJP+lA1vNheOSQlIvhwOyY8IgMakRp9D6Duned3j642MQ6kA88ky2EUdoEG3PWepTo2/ESriHbbHUnk662FC7gjQwGU20QbMG/mPcezb5OZOBJ4FAE1igZAyHH5rAFItJV4aQ6zjqg2/y4mH4L2XYqe/SSld/Jm2Sssn1r2FHXSRdnUeQeMjlHIlXP++/fKn43aHJ7RLbvMPiYo9uom13VMDwPzXb+0+b0TX5XDMsF5hcKyT3n76A3DXpP6S/IAhC6fgwz6bpTWuGNquhfHN8+tNZByVqvBLxX4DtHOOp2S6Df5GGjjZsg3SXHY706ntcZtUSLCdpxY7mcJK+JmcY83xF8Xa5OETf7OGz9pUabL5QBwZaBykNvAhs2VdbnFTmC/xHAj3szxB/W6cN4YxcXnQcS2/4Vktl6sJ8ph398/j0sj2gZjAuUFwXJhYAa3WwWcHU/x48vegMxsk3XamAjhZ25ICy7qWpEj0vb5fVBK/qpC4BIDF8f5/XRmho7GA2J5vgcGjkEjSzCCIXDLtZWWEgwJUCBpK7njBwowsQ6lNurDu6NarTvVCGG96yrF0F5Xp9f8HVUIb3NOf5qzs9b5vilL30RKOa7oLwcnb+y+bpo02ivpb2TDwEnpWnw3Ce3rCidCB3Jqzp84T5yJVXLDllojkG4xRlayQfo24Mf0dpcoUiFw1wA+iHrW4D/PfRix+IhTL2jnW30lHY6xhcMyfS4S5YHpqcpU7SppeB+OIqQkEeTDh5OLQzMmzVV8Nhv6Myecj3Or8KMgS1yHq8X9dilCkOQ3XeCTGtHKpkmJWStm+39cd2hxQWrqsiRYJJ9dyO3u+uwsTqk22MXFhLQwlxhHecdH4i3yft+hS+PXwXvT3++fzg8vjsNDr7xVIdi9VqmY0aHndmmyADjFSzsJj1hl2RSTSXz2Z4JKgmlfqfbAL5YmQ/ufKMD9lGQmTS3KgbwPwdejSM2tw52DWb3xzaAEuC7tK3dn5IE7ZuGwykszEsHtLTsOMaXeBQHa7ZCtmmDh30jAleGnvldrtSNlsDXfXuTVjT1866aMli0AENT3sJoMMnX0jF98pWtigkWEzHuWBgp3I0R+xTJH9ugCcL5h1lM1YCaBewkLEG3rAANROGUDOitHKl0E6jOj2SqBDadMNHHRzu1mRqm05yyYAgT8THDh7rj/8XfwfJ7A=='


def run(argv,check=True,timeout=20):
    p=subprocess.run(argv,check=False,capture_output=True,text=True,timeout=timeout,
                     env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'C'})
    if check and p.returncode:raise RuntimeError('command failed: '+argv[0]+' exit '+str(p.returncode))
    return p


def read_regular(path,owner,max_bytes=2097152,private=False):
    for parent in path.parents:
        if parent.is_symlink():raise RuntimeError('symlink parent rejected')
    fd=os.open(str(path),os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:
        s=os.fstat(f.fileno())
        if not stat.S_ISREG(s.st_mode) or s.st_uid!=owner or s.st_nlink!=1 or s.st_mode&(0o077 if private else 0o022):
            raise RuntimeError('unsafe source file')
        data=f.read(max_bytes+1)
    if len(data)>max_bytes:raise RuntimeError('source too large')
    return data


def identity():
    if sys.platform!='darwin':raise RuntimeError('macOS required')
    raw=run(['/usr/sbin/ioreg','-rd1','-c','IOPlatformExpertDevice']).stdout
    match=re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"',raw)
    if not match or hashlib.sha256(match.group(1).encode()).hexdigest()!='2b9d73883351aa41e92d596b14e725b4ca557d3c596df090fdee4b35ece64784':
        raise RuntimeError('wrong Mac')
    for kind,expected in [('Users',USER_UUID),('Groups',GROUP_UUID)]:
        raw=run(['/usr/bin/dscl','-plist','.','-read','/'+kind+'/mcp_andrea','GeneratedUID','PrimaryGroupID']).stdout
        d={k.split(':')[-1]:v for k,v in plistlib.loads(raw.encode()).items()}
        if d.get('GeneratedUID')!=[expected] or d.get('PrimaryGroupID')!=['5000']:raise RuntimeError('dedicated identity changed')
    if run(['/usr/bin/id','-u','mcp_andrea']).stdout.strip()!='5000':raise RuntimeError('wrong uid')
    if {'0','80'}&set(run(['/usr/bin/id','-G','mcp_andrea']).stdout.split()):raise RuntimeError('admin group refused')
    attrs=['UserShell','NFSHomeDirectory']
    if os.geteuid()==0:attrs+=['AuthenticationAuthority','Password']
    raw=run(['/usr/bin/dscl','-plist','.','-read','/Users/mcp_andrea']+attrs).stdout
    d={k.split(':')[-1]:v for k,v in plistlib.loads(raw.encode()).items()}
    expected={'UserShell':['/usr/bin/false'],'NFSHomeDirectory':['/var/empty'],
              'AuthenticationAuthority':[';DisabledUser;'],'Password':['*']}
    if any(d.get(key)!=expected[key] for key in attrs):raise RuntimeError('dedicated login configuration changed')


def active():
    raw=run(['/bin/ps','-axo','uid=,pid=,stat=']).stdout
    return [int(x.split()[1]) for x in raw.splitlines() if len(x.split())==3 and x.split()[0]=='5000' and not x.split()[2].startswith('Z')]


def empty_old_workspace():
    count=0
    for p in OLDWORK.rglob('*'):
        count+=1
        if count>10000 or p.is_symlink() or not p.is_dir():
            raise RuntimeError('old workspace now contains data; migration needs reviewed copy')


def check():
    identity()
    if active():raise RuntimeError('uid5000 in use')
    destinations=(BASE,AREA,PLIST) if os.geteuid()==0 else (BASE,AREA)
    if any(p.exists() or p.is_symlink() for p in destinations):raise RuntimeError('migration destination exists')
    for parent in (BASE.parent,PLIST.parent):
        s=parent.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise RuntimeError('untrusted install parent')
    original=read_regular(OLDPLIST,501)
    if hashlib.sha256(original).hexdigest()!=OLDHASH:raise RuntimeError('old agent plist changed')
    if run(['/bin/launchctl','print','gui/501/'+OLDLABEL],check=False).returncode:raise RuntimeError('old agent not loaded')
    disabled=run(['/bin/launchctl','print-disabled','gui/501']).stdout
    if re.search(re.escape(OLDLABEL)+r'"?\s*=>\s*true',disabled):raise RuntimeError('old agent explicitly disabled')
    proof=json.loads(read_regular(PREFLIGHT/'receipt.json',0))
    if proof.get('status')!='preflight_passed' or proof.get('remaining_uid5000_processes')!=0 or len(proof.get('checks',[]))!=15 or not all(x.get('passed') is True for x in proof['checks']):
        raise RuntimeError('dedicated account preflight not passed')
    if os.geteuid()==0 and hashlib.sha256(read_regular(PREFLIGHT/'preflight_installer.py',0)).hexdigest()!=PREFLIGHT_HASH:
        raise RuntimeError('preflight source changed')
    if hashlib.sha256(read_regular(STAGING/WHEEL,501)).hexdigest()!=WHEELHASH:raise RuntimeError('dependency hash mismatch')
    empty_old_workspace()
    return {'preparation_ready':True,'root_checks_pending':[] if os.geteuid()==0 else
            ['daemon_destination_absent','preflight_source_sha256','login_disabled'],
            'machine':'mac_noleggio','uid':5000,'old_workspace_empty':True,
            'action':'migrate_central_agent_only','new_workspace':str(AREA/'workspace'),
            'automatic_rollback':True,'admin_telegram_route_changed':False}


def newfile(path,data,mode=0o644,uid=0,gid=0):
    fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'wb') as f:
        os.fchown(f.fileno(),uid,gid);os.fchmod(f.fileno(),mode)
        f.write(data);f.flush();os.fsync(f.fileno())


def save_receipt(receipt):
    fd,name=tempfile.mkstemp(dir=str(BASE),prefix='.receipt-')
    with os.fdopen(fd,'w') as f:
        os.fchmod(f.fileno(),0o644);json.dump(receipt,f,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(name,str(BASE/'receipt.json'))


def child(args,timeout=40):
    return subprocess.run([os.path.realpath(sys.executable),'-I','-B']+args,
        user=5000,group=5000,extra_groups=[5000],umask=0o077,close_fds=True,start_new_session=True,
        cwd='/',env={'PATH':'/usr/bin:/bin','HOME':'/var/empty','LANG':'en_US.UTF-8'},
        capture_output=True,text=True,timeout=timeout)


def clear_children():
    if active():
        p=child(['-c','import sys;sys.path.insert(0,'+repr(str(BASE/'code'))+');from mac_guard import stop_dedicated_children;stop_dedicated_children()'],10)
        if p.returncode:raise RuntimeError('dedicated cleanup failed')
    if active():raise RuntimeError('dedicated processes remain')


def restore_old(receipt):
    if PLIST.exists():
        data=read_regular(PLIST,0)
        if hashlib.sha256(data).hexdigest()!=receipt.get('new_plist_sha256'):raise RuntimeError('new plist changed; rollback refused')
        run(['/bin/launchctl','bootout','system/'+LABEL],check=False)
        if run(['/bin/launchctl','print','system/'+LABEL],check=False).returncode==0:
            raise RuntimeError('new daemon still loaded; rollback stopped')
        os.replace(str(PLIST),str(BASE/'backup/new-daemon-disabled.plist'))
    clear_children()
    if hashlib.sha256(read_regular(OLDPLIST,501)).hexdigest()!=OLDHASH:raise RuntimeError('old plist changed; restore refused')
    run(['/bin/launchctl','enable','gui/501/'+OLDLABEL])
    if run(['/bin/launchctl','print','gui/501/'+OLDLABEL],check=False).returncode:
        run(['/bin/launchctl','bootstrap','gui/501',str(OLDPLIST)])
    run(['/bin/launchctl','print','gui/501/'+OLDLABEL])
    receipt.update(status='rolled_back',time=time.time(),old_agent_restored=True,new_data_preserved=True)
    save_receipt(receipt)


def apply():
    check()
    source=globals().get('APPROVED_SOURCE')
    if not isinstance(source,bytes):raise RuntimeError('use the SHA-verifying local launcher')
    payload=json.loads(zlib.decompress(base64.b64decode(PAYLOAD)))
    expected={'file_tools.py','file_schema.py','shell_common.py','mac_guard.py','mac_clock.py','mac_policy.py','mac_child.py','mac_watchdog.py','mac_shell.py','agent_shell.py','mac_agent.py','selftest.py'}
    if set(payload)!=expected:raise RuntimeError('unexpected code payload')
    wheel=read_regular(STAGING/WHEEL,501)
    if hashlib.sha256(wheel).hexdigest()!=WHEELHASH:raise RuntimeError('dependency changed')
    token=read_regular(OLD/'agent.token',501,4096,True).strip()
    if not re.fullmatch(rb'[A-Za-z0-9_-]{43,256}',token):raise RuntimeError('invalid existing credential')
    guard=os.open(str(OLD/'workspace-operations/guard'),os.O_RDWR|os.O_NOFOLLOW)
    fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:
        empty_old_workspace()
        BASE.mkdir(mode=0o755);(BASE/'backup').mkdir(mode=0o700)
        before={'old_plist_sha256':OLDHASH,'old_label':OLDLABEL,'old_disabled':False,'user_uuid':USER_UUID,
                'new_base_before':None,'new_workspace_before':None,'source_sha256':hashlib.sha256(source).hexdigest()}
        newfile(BASE/'backup/before.json',json.dumps(before,indent=2).encode(),0o600)
        newfile(BASE/'backup/old-agent.plist',read_regular(OLDPLIST,501),0o600)
        newfile(BASE/'installer.py',source,0o500)
        receipt={'status':'prepared','time':time.time(),'source_sha256':before['source_sha256'],'machine':'mac_noleggio'}
        save_receipt(receipt)
        try:
            AREA.mkdir(mode=0o755)
            for p in (AREA/'workspace',AREA/'workspace/.tmp',BASE/'state'):
                p.mkdir(mode=0o700);os.chown(str(p),5000,5000)
            (BASE/'private').mkdir(mode=0o750);os.chown(str(BASE/'private'),0,5000)
            newfile(BASE/'private/agent.token',token+b'\n',0o640,0,5000)
            del token
            (BASE/'code').mkdir(mode=0o755)
            for name,body in payload.items():newfile(BASE/'code'/name,body.encode(),0o444)
            vendor=BASE/'code/vendor';vendor.mkdir(mode=0o755)
            with zipfile.ZipFile(io.BytesIO(wheel)) as z:
                if len(z.infolist())>200 or sum(x.file_size for x in z.infolist())>10485760:
                    raise RuntimeError('dependency archive too large')
                for item in z.infolist():
                    parts=Path(item.filename).parts
                    if not parts or Path(item.filename).is_absolute() or '..' in parts or item.file_size>2097152 or stat.S_ISLNK(item.external_attr>>16):raise RuntimeError('unsafe dependency archive')
                    dest=vendor/item.filename
                    if item.is_dir():dest.mkdir(mode=0o755,parents=True,exist_ok=True)
                    else:
                        dest.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
                        newfile(dest,z.read(item),0o444)
            p=child([str(BASE/'code/selftest.py')])
            newfile(BASE/'selftest.log',(p.stdout+'\n'+p.stderr).encode()[-65536:])
            if p.returncode:raise RuntimeError('new agent selftest failed; see selftest.log')
            if active():raise RuntimeError('selftest left running processes')
            data=plistlib.dumps({'Label':LABEL,'ProgramArguments':[os.path.realpath(sys.executable),'-I','-B',str(BASE/'code/mac_agent.py')],
                'UserName':'mcp_andrea','GroupName':'mcp_andrea','WorkingDirectory':str(AREA/'workspace'),
                'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,'ExitTimeOut':10,'ProcessType':'Background',
                'Umask':63,'StandardOutPath':'/dev/null','StandardErrorPath':'/dev/null',
                'EnvironmentVariables':{'PATH':'/usr/bin:/bin','HOME':str(AREA/'workspace'),'PYTHONDONTWRITEBYTECODE':'1'}},sort_keys=True)
            receipt['new_plist_sha256']=hashlib.sha256(data).hexdigest();save_receipt(receipt)
            run(['/bin/launchctl','disable','gui/501/'+OLDLABEL])
            run(['/bin/launchctl','bootout','gui/501/'+OLDLABEL])
            empty_old_workspace()
            newfile(PLIST,data,0o644)
            started=time.time()
            run(['/bin/launchctl','bootstrap','system',str(PLIST)])
            ready=None
            for _ in range(90):
                path=BASE/'state/connected.json'
                if path.exists():
                    ready=json.loads(read_regular(path,5000,4096,True))
                    if ready.get('uid')==5000 and ready.get('version')=='0.9-rental-1' and ready.get('time',0)>=started and ready.get('connected') is True:break
                time.sleep(1)
            else:raise RuntimeError('new agent gateway connection timeout')
            status=run(['/bin/launchctl','print','system/'+LABEL]).stdout
            if not re.search(r'\bpid = '+str(ready['pid'])+r'\b',status):raise RuntimeError('agent PID mismatch')
            receipt.update(status='active',time=time.time(),uid=5000,agent_pid=ready['pid'],new_workspace=str(AREA/'workspace'),
                shell_default='disabled',shell_network='disabled',rollback_available=True,old_files_preserved=True,boot_start=True)
            save_receipt(receipt)
        except Exception as exc:
            receipt['failure']=type(exc).__name__+': '+str(exc)[:300]
            try:restore_old(receipt)
            except Exception as cleanup:
                receipt.update(status='rollback_requires_review',rollback_failure=type(cleanup).__name__+': '+str(cleanup)[:300]);save_receipt(receipt)
            print(json.dumps(receipt,indent=2));raise SystemExit(1)
        print(json.dumps(receipt,indent=2))
    finally:os.close(guard)


def main():
    if len(sys.argv)!=2 or sys.argv[1] not in ('--check','--apply','--rollback'):raise SystemExit('use --check/--apply/--rollback')
    if sys.argv[1]=='--check':print(json.dumps(check(),indent=2));return
    if os.getuid()!=0 or os.geteuid()!=0:raise SystemExit('physical administrator authorization required')
    identity();os.umask(0o022)
    # Shared with both preflight versions: never run their uid5000 jobs together.
    fd=os.open('/var/run/mcp-andrea-shell-preflight.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:
        if sys.argv[1]=='--apply':apply()
        else:restore_old(json.loads(read_regular(BASE/'receipt.json',0)))
    finally:os.close(fd)

if __name__=='__main__':main()
